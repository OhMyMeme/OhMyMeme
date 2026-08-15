"""全局快捷键 - 跨平台热键注册，自动降级容错"""

import logging
import sys
import threading
import time

logger = logging.getLogger(__name__)


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

            # suppress=True 会安装 WH_KEYBOARD_LL 状态机，吞掉按键事件
            keyboard.add_hotkey(hotkey, callback, suppress=False)
            self._backend = "keyboard"
            self._active = True
            logger.info(f"全局快捷键已注册 (keyboard): {hotkey}")
            return True
        except ImportError:
            return False
        except Exception as e:
            logger.warning(f"keyboard 库注册失败: {e}")
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

    def unregister(self):
        """注销全局快捷键"""
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

    def __del__(self):
        self.unregister()
