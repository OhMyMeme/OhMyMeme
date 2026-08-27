"""全局快捷键 - 跨平台热键注册，自动降级容错"""

import logging
import sys
import threading
import time

logger = logging.getLogger(__name__)

# keyboard 库监听线程存活检查周期（秒）
KEYBOARD_WATCH_INTERVAL = 5.0

# 独立的热键事件日志（追加到 data_dir/hotkey.log，便于日后排查热键失效/自愈）
_file_logger = None
_file_logger_tried = False
_file_logger_lock = threading.Lock()


def _get_file_logger():
    """延迟初始化并返回写 hotkey.log 的独立 logger。

    日志路径来自 Config.data_dir；惰性创建，失败（无 config/路径不可写）则降级
    为普通 logger，绝不影响运行。
    """
    global _file_logger, _file_logger_tried
    if _file_logger is not None:
        return _file_logger
    if _file_logger_tried:
        return logger
    with _file_logger_lock:
        if _file_logger is not None:
            return _file_logger
        _file_logger_tried = True
        try:
            from .config import get_config

            cfg = get_config()
            data_dir = cfg.data_dir
            data_dir.mkdir(parents=True, exist_ok=True)
            path = data_dir / "hotkey.log"
            fl = logging.getLogger("ohmymeme.hotkey.file")
            fl.setLevel(logging.INFO)
            fl.propagate = False
            handler = logging.FileHandler(str(path), encoding="utf-8")
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            )
            fl.addHandler(handler)
            _file_logger = fl
            logger.info("热键事件日志将写入 %s", path)
            return fl
        except Exception as e:
            logger.warning("热键事件日志初始化失败（忽略）: %s", e)
            return logger


def _log_hotkey_event(level, msg):
    """写一条热键事件到文件日志，并同步到常规日志（控制台）。"""
    target = _get_file_logger()
    getattr(target, level)(msg)
    getattr(logger, level)(msg)


class GlobalHotkey:
    """全局快捷键管理器，自动尝试多种后端"""

    def __init__(self):
        self._listener = None
        self._thread = None
        self._active = False
        self._callback = None
        self._hotkey = None
        self._backend = None
        self._polling = False
        self._watchdog_stop = None
        self._safe_callback = None
        self._reregister_pending = False
        # 序列化 _reregister_keyboard 与 unregister，避免注销与重注册并发交错
        self._reregister_lock = threading.Lock()

    def register(self, hotkey: str, callback) -> bool:
        """注册全局快捷键，自动尝试 keyboard → pynput → 轮询降级"""
        self._callback = callback
        self._hotkey = hotkey

        # 尝试 keyboard 库（最快，但Windows hook可能崩溃）
        if self._try_keyboard(hotkey, callback):
            return True

        # 备选：pynput
        if self._try_pynput(hotkey, callback):
            return True

        # 最终降级：轮询检测（每200ms检查一次，低占用）
        logger.warning("全局快捷键库均不可用，启用轮询降级模式 (每200ms)")
        self._start_polling(hotkey, callback)
        return True

    def _try_keyboard(self, hotkey: str, callback) -> bool:
        # macOS: keyboard 库 darwin 后端需 root 权限，改用 pynput（CGEventTap）
        if sys.platform == "darwin":
            return False
        try:
            import keyboard

            def make_safe(fn):
                def _safe_callback():
                    # keyboard 在处理线程调用该回调；若此处抛异常，keyboard 的
                    # processing_thread（pre_process_event 无保护）会崩溃退出，
                    # 导致所有热键在运行期永久失效（进程仍存活、需重启软件恢复）。
                    try:
                        fn()
                    except Exception:
                        logger.exception("全局快捷键回调异常（已吞掉避免杀死处理线程）")
                        _log_hotkey_event(
                            "error", "热键回调异常（已吞掉，未杀死处理线程）"
                        )

                return _safe_callback

            self._safe_callback = make_safe(callback)

            # suppress=True 会安装 WH_KEYBOARD_LL 状态机，吞掉按键事件
            keyboard.add_hotkey(hotkey, self._safe_callback, suppress=False)
            self._backend = "keyboard"
            self._active = True
            self._start_keyboard_watchdog()
            logger.info(f"全局快捷键已注册 (keyboard): {hotkey}")
            _log_hotkey_event("info", "热键已注册 (keyboard): %s" % hotkey)
            return True
        except ImportError:
            return False
        except Exception as e:
            logger.warning(f"keyboard 库注册失败: {e}")
            return False

    def _start_keyboard_watchdog(self):
        """启动监听线程存活守护：检测 keyboard 内部监听/处理线程死亡并自动重注册。

        keyboard 0.13.5 的 GenericListener 处理线程一旦因未捕获异常崩溃即永久失效
        （进程仍存活、界面正常，但热键无响应，需重启软件才能恢复）。此守护周期性
        检查两个内部线程存活，死后自动重新注册热键，避免用户手动重启。
        """
        if self._watchdog_stop is not None:
            return  # 已在监控运行，避免重复
        stop = threading.Event()
        self._watchdog_stop = stop

        def watch():
            while not stop.wait(KEYBOARD_WATCH_INTERVAL):
                try:
                    import keyboard

                    listener = getattr(keyboard, "_listener", None)
                    if listener is None:
                        continue
                    lt = getattr(listener, "listening_thread", None)
                    pt = getattr(listener, "processing_thread", None)
                    dead = (lt is not None and not lt.is_alive()) or (
                        pt is not None and not pt.is_alive()
                    )
                    if dead and self._backend == "keyboard" and self._safe_callback:
                        logger.error(
                            "全局快捷键监听/处理线程已退出，尝试自动重新注册热键"
                        )
                        _log_hotkey_event(
                            "error", "监听/处理线程已退出，尝试自动重新注册热键"
                        )
                        # 与 unregister 用同一锁互斥：若注销已完成则停止标志已置位，
                        # 重注册函数会因该标志直接返回，避免注销后被重新挂上
                        self._reregister_keyboard(listener)
                except Exception:
                    logger.exception("快捷键守护线程检查异常")

        t = threading.Thread(target=watch, daemon=True)
        t.start()

    def _reregister_keyboard(self, listener):
        """重置 keyboard 监听状态并重新注册热键，返回是否成功。

        与 unregister 持同一 `_reregister_lock`，并在锁内复查 `_watchdog_stop`：
        - 若注销已启动（停止标志已置位或回调已清空），直接返回 False，不重新挂热键；
        - 若 `add_hotkey` 失败，置 `_reregister_pending=True` 并返回 False，守护线程
          下一周期会继续重试，而不是误报成功后就再也不重试。
        """
        with self._reregister_lock:
            # 注销已开始（回调已清空，或停止事件已置位）：不允许重新挂热键，
            # 也避免把已清空的回调传进 add_hotkey
            stopped = self._safe_callback is None or (
                self._watchdog_stop is not None
                and getattr(self._watchdog_stop, "is_set", lambda: False)()
            )
            if stopped:
                return False
            try:
                import keyboard

                if self._hotkey:
                    try:
                        keyboard.remove_hotkey(self._hotkey)
                    except Exception:
                        pass
                # 线程崩溃后 listening 标志仍为 True，需重置才能重启线程
                try:
                    listener.listening = False
                    listener.start_if_necessary()
                except Exception as e:
                    logger.warning("keyboard 监听可能无法直接重启，改用重新 add: %s", e)
                try:
                    keyboard.add_hotkey(
                        self._hotkey, self._safe_callback, suppress=False
                    )
                except Exception as e:
                    self._reregister_pending = True
                    logger.warning("自动重新注册快捷键失败: %s", e)
                    _log_hotkey_event("error", "自动重新注册快捷键失败: %s" % e)
                    return False
                self._reregister_pending = False
                logger.info(f"全局快捷键已自动重新注册: {self._hotkey}")
                _log_hotkey_event("info", "热键已自动重新注册: %s" % self._hotkey)
                return True
            except Exception:
                logger.exception("自动重新注册快捷键失败")
                return False

    def _try_pynput(self, hotkey: str, callback) -> bool:
        try:
            from pynput import keyboard as pynput_keyboard

            parts = [p.strip().lower() for p in hotkey.split("+")]
            required_keys = set()
            main_key = None
            key_map = {
                "ctrl": pynput_keyboard.Key.ctrl,
                "alt": pynput_keyboard.Key.alt,
                "shift": pynput_keyboard.Key.shift,
                "win": pynput_keyboard.Key.cmd,
                "cmd": pynput_keyboard.Key.cmd,
            }
            for p in parts:
                if p in key_map:
                    required_keys.add(key_map[p])
                else:
                    main_key = p

            pressed = set()

            def on_press(key):
                try:
                    pressed.add(key)
                    if all(mod in pressed for mod in required_keys):
                        if main_key:
                            if isinstance(key, pynput_keyboard.Key):
                                key_name = key.name
                            else:
                                key_name = key.char
                            if key_name and key_name.lower() == main_key.lower():
                                callback()
                except Exception:
                    pass

            def on_release(key):
                try:
                    pressed.discard(key)
                except Exception:
                    pass

            self._listener = pynput_keyboard.Listener(
                on_press=on_press, on_release=on_release
            )
            self._listener.daemon = True
            self._listener.start()
            self._backend = "pynput"
            self._active = True
            logger.info(f"全局快捷键已注册 (pynput): {hotkey}")
            _log_hotkey_event("info", "热键已注册 (pynput): %s" % hotkey)
            return True
        except ImportError:
            return False
        except Exception as e:
            logger.warning(f"pynput 注册失败: {e}")
            return False

    def _start_polling(self, hotkey: str, callback):
        """轮询模式：模拟检测热键，每200ms一次"""
        self._backend = "polling"
        self._polling = True
        self._active = True

        # 解析热键
        parts = [p.strip().lower() for p in hotkey.split("+")]
        main_key = parts[-1] if parts else ""
        mod_keys = set(parts[:-1])

        import keyboard as kb_module

        def poll():
            while self._polling:
                try:
                    all_pressed = True
                    for mod in mod_keys:
                        try:
                            if not kb_module.is_pressed(mod):
                                all_pressed = False
                                break
                        except Exception:
                            all_pressed = False
                            break
                    if all_pressed and main_key:
                        try:
                            if kb_module.is_pressed(main_key):
                                callback()
                                time.sleep(0.3)
                        except Exception:
                            pass
                except Exception:
                    pass
                time.sleep(0.2)

        self._thread = threading.Thread(target=poll, daemon=True)
        self._thread.start()
        logger.info(f"全局快捷键轮询模式已启动: {hotkey}")
        _log_hotkey_event("info", "热键轮询降级模式已启动: %s" % hotkey)

    def unregister(self):
        """注销全局快捷键"""
        # 与 _reregister_keyboard 持同一锁：等待进行中的重注册完成后再注销。
        # 置位停止标志 + 清空回调，使未开始的重注册会因标志/回调被清而直接返回，
        # 避免注销后被守护线程重新挂上或传入已清空的回调。
        with self._reregister_lock:
            if self._watchdog_stop is not None:
                self._watchdog_stop.set()
                self._watchdog_stop = None
            if self._backend == "keyboard":
                try:
                    import keyboard

                    if self._hotkey:
                        keyboard.remove_hotkey(self._hotkey)
                except Exception:
                    pass
            elif self._backend == "pynput":
                if self._listener:
                    try:
                        self._listener.stop()
                    except Exception:
                        pass
                    self._listener = None
            elif self._backend == "polling":
                self._polling = False
                if self._thread:
                    self._thread = None
            self._active = False
            self._safe_callback = None

    def __del__(self):
        self.unregister()
