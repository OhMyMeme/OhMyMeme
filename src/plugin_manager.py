"""插件系统 - 插件发现、校验、加载、隔离与注册表管理"""

import hashlib
import importlib.util
import json
import logging
import os
import queue
import re
import sys
import tempfile
import threading
import traceback
from pathlib import Path

logger = logging.getLogger(__name__)

# 插件 API 版本（manifest api_version 必须匹配才加载）
PLUGIN_API_VERSION = 1

# 各阶段超时（秒）：on_load 加载、普通回调、交互式 js_api（文件对话框可能耗时）
LOAD_TIMEOUT = 15.0
HANDLER_TIMEOUT = 10.0
_API_TIMEOUT = 120.0

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_REPO_RE = re.compile(r"^(https://|git@|ssh://)")
_KNOWN_WINDOWS = ("main", "settings")
_KNOWN_PERMISSIONS = frozenset(
    {
        "route",
        "main_api",
        "settings_api",
        "assets:serve",
        "settings:section",
        "buttons",
        "startup",
        "window",
        "host:evaluate_js",
    }
)
_MIME = {
    ".css": "text/css",
    ".js": "text/javascript",
    ".html": "text/html",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}


class PluginInfo:
    """单个插件的 manifest 信息与运行期注册表"""

    def __init__(self, plugin_dir: Path, manifest: dict):
        self.dir = plugin_dir
        self.manifest = manifest
        self.id = manifest["id"]
        self.name = str(manifest.get("name") or self.id)
        self.version = str(manifest.get("version") or "0.0.0")
        self.repo = str(manifest.get("repo") or "")
        self.description = str(manifest.get("description") or "")
        self.author = str(manifest.get("author") or "")
        self.entry = str(manifest.get("entry") or "")
        self.sandbox = bool(manifest.get("sandbox"))
        windows = manifest.get("windows")
        if not isinstance(windows, list):
            windows = ["main"]
        self.windows = tuple(w for w in windows if w in _KNOWN_WINDOWS) or ("main",)
        perms = manifest.get("permissions")
        if not isinstance(perms, list):
            perms = []
        unknown = [p for p in perms if p not in _KNOWN_PERMISSIONS]
        if unknown:
            logger.warning("plugin %s 声明了未知权限（已忽略）: %s", self.id, unknown)
        self.permissions = frozenset(p for p in perms if p in _KNOWN_PERMISSIONS)
        deps = manifest.get("dependencies")
        if not isinstance(deps, list):
            deps = []
        self.dependencies = tuple(str(d).strip() for d in deps if str(d).strip())
        # loaded 运行中 / disabled 用户禁用或运行期熔断 / failed 加载失败
        self.status = "failed"
        self.reason = ""
        self.module = None
        self.on_unload = None
        self.on_settings_changed = None
        self.vendor_path = None
        # 注册表（disable/unload 时统一清空，实现逻辑注销）
        self.routes = []
        self.main_api = {}
        self.settings_api = {}
        self.assets = {}
        self.sections = []
        self.buttons = []
        self.button_handler = None
        self.button_constraints = {"hide": set(), "order": {}}
        self.startup = {}
        self.window = {}

    @property
    def loaded(self) -> bool:
        return self.status == "loaded"

    def clear_registry(self):
        """清空全部注册项（禁用/卸载时防残留调用）"""
        self.routes = []
        self.main_api = {}
        self.settings_api = {}
        self.assets = {}
        self.sections = []
        self.buttons = []
        self.button_handler = None
        self.button_constraints = {"hide": set(), "order": {}}
        self.startup = {}
        self.window = {}


class PluginContext:
    """传给插件 on_load 的能力上下文（带权限门控）"""

    def __init__(self, manager: "PluginManager", plugin: PluginInfo):
        self._m = manager
        self._p = plugin

    @property
    def id(self) -> str:
        return self._p.id

    @property
    def data_dir(self) -> Path:
        """插件私有运行数据目录（LOCALAPPDATA/OhMyMeme/plugins_data/<id>）"""
        d = self._m.cfg.data_dir / "plugins_data" / self._p.id
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def settings(self) -> dict:
        """插件只读设置快照（manifest 无关，由设置页写入）"""
        return self._m.get_settings(self._p.id)

    def log(self, msg, level="info"):
        """写应用日志（带插件前缀）"""
        getattr(logger, level, logger.info)("[plugin:%s] %s", self._p.id, msg)

    def _require(self, perm: str):
        if perm not in self._p.permissions:
            raise PermissionError(f"插件 {self._p.id} 未声明权限 {perm}")

    def register_route(self, rule: str, fn):
        """注册自定义 Bottle 路由（需权限 route；规则需以 / 开头）"""
        self._require("route")
        if not isinstance(rule, str) or not rule.startswith("/"):
            raise ValueError("route 规则必须以 / 开头")
        if not callable(fn):
            raise TypeError("route 处理器必须可调用")
        self._p.routes.append((rule, fn))

    def register_main_api(self, name: str, fn):
        """注册主窗口插件方法（经 JsApi.plugin_call 分发，需权限 main_api）"""
        self._require("main_api")
        if not isinstance(name, str) or not name or not name.isidentifier():
            raise ValueError("main_api 方法名必须为合法标识符")
        self._p.main_api[name] = fn

    def register_settings_api(self, name: str, fn):
        """注册设置窗口插件方法（SettingsApi.plugin_call 分发，需权限 settings_api）"""
        self._require("settings_api")
        if not isinstance(name, str) or not name or not name.isidentifier():
            raise ValueError("settings_api 方法名必须为合法标识符")
        self._p.settings_api[name] = fn

    def register_css(self, window: str, relpath: str):
        """注册注入指定窗口的 CSS 资产（插件目录内相对路径，需权限 assets:serve）"""
        self._register_asset(window, relpath, "css")

    def register_js(self, window: str, relpath: str):
        """注册注入指定窗口的 JS 资产（需权限 assets:serve）"""
        self._register_asset(window, relpath, "js")

    def _register_asset(self, window: str, relpath: str, kind: str):
        self._require("assets:serve")
        if window not in _KNOWN_WINDOWS:
            raise ValueError(f"未知窗口: {window}")
        target = (self._p.dir / relpath).resolve()
        if target != self._p.dir.resolve() and not target.is_relative_to(
            self._p.dir.resolve()
        ):
            raise ValueError("资产路径必须位于插件目录内")
        if not target.is_file():
            raise FileNotFoundError(f"资产不存在: {relpath}")
        slot = self._p.assets.setdefault(window, {"css": [], "js": []})
        rel = os.path.relpath(target, self._p.dir).replace("\\", "/")
        if rel not in slot[kind]:
            slot[kind].append(rel)

    def register_settings_section(self, html: str):
        """注册设置窗口「插件」分组内的 HTML 片段（需权限 settings:section）"""
        self._require("settings:section")
        if not isinstance(html, str) or not html.strip():
            raise ValueError("section 必须为非空 HTML 字符串")
        self._p.sections.append(html)

    def register_button(self, button: dict):
        """注册主窗口顶栏按钮 {key,label,icon?,order?}（需权限 buttons）"""
        self._require("buttons")
        if not isinstance(button, dict) or not button.get("key"):
            raise ValueError("button 必须为含 key 的字典")
        key = str(button["key"])
        if any(b.get("key") == key for b in self._p.buttons):
            raise ValueError(f"重复的按钮 key: {key}")
        self._p.buttons.append(
            {
                "key": key,
                "label": str(button.get("label") or key),
                "icon": str(button.get("icon") or ""),
                "order": int(button.get("order") or 100),
            }
        )

    def register_button_handler(self, fn):
        """注册按钮点击处理器 fn(key)（需权限 buttons）"""
        self._require("buttons")
        if not callable(fn):
            raise TypeError("button handler 必须可调用")
        self._p.button_handler = fn

    def register_button_constraints(self, hide=None, order=None):
        """约束核心顶栏按钮 hide=[key]/order={key: 位置}（需权限 buttons）"""
        self._require("buttons")
        if hide:
            self._p.button_constraints["hide"].update(str(k) for k in hide)
        if isinstance(order, dict):
            for k, v in order.items():
                self._p.button_constraints["order"][str(k)] = int(v)

    def set_startup_override(
        self, video_src=None, bg_color=None, duration_ms=None, media_type=None
    ):
        """覆盖启动动画媒体源/底色/时长（需权限 startup；多插件按 id 序后者生效）

        duration_ms 供图片/动图指定展示时长（0/None=前端默认），media_type 可显式
        指定 video/image（空则前端按扩展名判断）。
        """
        self._require("startup")
        if video_src:
            self._p.startup["video_src"] = str(video_src)
        if bg_color:
            self._p.startup["bg_color"] = str(bg_color)
        if duration_ms:
            self._p.startup["duration_ms"] = int(duration_ms)
        if media_type:
            self._p.startup["media_type"] = str(media_type)

    def set_window_params(self, width=None, height=None):
        """覆盖主窗口初始尺寸（需权限 window；0/缺失项不覆盖）"""
        self._require("window")
        if width:
            self._p.window["width"] = int(width)
        if height:
            self._p.window["height"] = int(height)

    def evaluate_js(self, code: str):
        """向主窗口推送 JS（需权限 host:evaluate_js）"""
        self._require("host:evaluate_js")
        self._m.evaluate_js(code)

    def save_settings(self, data: dict):
        """持久化插件自有设置（与 manifest 无关，自动合并）"""
        self._m.save_settings(self._p.id, data)


class PluginManager:
    """插件管理器：发现、校验、加载、熔断与注册表聚合"""

    def __init__(self):
        self.cfg = None
        self.state_path = None
        self._state = {"disabled": []}
        self._settings = {}
        self._plugins = {}
        self._lock = threading.RLock()
        self._inited = False

    # --- 生命周期 ---

    def init(self, cfg):
        """扫描插件目录并加载全部可用插件（单个失败不影响其余）"""
        if self._inited:
            return
        self._inited = True
        self.cfg = cfg
        self.state_path = cfg.data_dir / "plugins_state.json"
        self._load_state()
        self._migrate_settings_location()
        for plugin_dir in self._iter_candidate_dirs():
            self._discover_one(plugin_dir)

    def unload(self):
        """退出时调用各插件 on_unload 并清空注册表（异常隔离）"""
        with self._lock:
            plugins = [p for p in self._plugins.values() if p.loaded]
        for p in plugins:
            if p.on_unload:
                self._invoke(p.id, p.on_unload, (), {}, LOAD_TIMEOUT)
            p.clear_registry()
            self._remove_vendor(p)

    # --- 发现与加载 ---

    def _iter_candidate_dirs(self):
        """候选插件目录：config plugin_dirs（开发直连或集合）+ 数据目录 plugins/"""
        bases = []
        for raw in self.cfg.get("plugin_dirs") or []:
            if raw:
                bases.append(Path(str(raw)).expanduser())
        bases.append(self.cfg.data_dir / "plugins")
        out = []
        for base in bases:
            try:
                if (base / "plugin.json").exists():
                    out.append(base)
                elif base.is_dir():
                    out.extend(
                        sorted(
                            d
                            for d in base.iterdir()
                            if d.is_dir() and (d / "plugin.json").exists()
                        )
                    )
            except OSError as e:
                logger.warning("plugin scan %s failed: %s", base, e)
        return out

    def _discover_one(self, plugin_dir: Path):
        """读取并校验单个 plugin.json，失败仅记日志跳过"""
        try:
            with open(plugin_dir / "plugin.json", "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("plugin manifest 读取失败 %s: %s", plugin_dir, e)
            return
        if not isinstance(manifest, dict) or not isinstance(manifest.get("id"), str):
            logger.warning("plugin manifest 缺少 id: %s", plugin_dir)
            return
        pid = manifest["id"]
        if not _ID_RE.match(pid):
            logger.warning("plugin id 非法: %r (%s)", pid, plugin_dir)
            return
        if (
            not str(manifest.get("name") or "").strip()
            or not str(manifest.get("version") or "").strip()
        ):
            logger.warning("plugin 缺少 name/version: %s", plugin_dir)
            return
        with self._lock:
            if pid in self._plugins:
                logger.warning("plugin id 重复，忽略后发现者: %s (%s)", pid, plugin_dir)
                return
            info = PluginInfo(plugin_dir, manifest)
            self._plugins[pid] = info
        self._prepare(info)

    def _prepare(self, info: PluginInfo):
        """校验 api_version/sandbox/依赖并加载 entry（全部异常隔离）"""
        try:
            if int(info.manifest.get("api_version", -1)) != PLUGIN_API_VERSION:
                self._fail(info, f"api_version 不支持（需 {PLUGIN_API_VERSION}）")
                return
            if info.sandbox:
                self._fail(info, "沙箱模式将在 v0.8 提供，当前版本跳过加载")
                return
            repo = info.repo
            if repo and not _REPO_RE.match(repo):
                self._fail(info, f"repo 非法 URL: {repo[:60]}")
                return
            if info.id in self._state.get("disabled", []):
                info.status = "disabled"
                info.reason = "user_disabled"
                return
            self._add_vendor(info)
            missing = self._missing_deps(info)
            if missing:
                self._fail(info, f"缺少依赖: {', '.join(missing)}")
                return
            if not info.entry:
                info.status = "loaded"
                info.reason = ""
                logger.info("plugin %s 已加载（纯资产插件）", info.id)
                return
            entry = (info.dir / info.entry).resolve()
            if entry != info.dir.resolve() and not entry.is_relative_to(
                info.dir.resolve()
            ):
                self._fail(info, "entry 路径必须位于插件目录内")
                return
            if not entry.is_file():
                self._fail(info, f"entry 文件不存在: {info.entry}")
                return
            modname = f"ohmymeme_plugin_{info.id.replace('-', '_')}"
            spec = importlib.util.spec_from_file_location(modname, entry)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            info.module = module
            on_load = getattr(module, "on_load", None)
            if callable(on_load):
                info.status = "loading"
                ok, result = self._invoke(
                    info.id, on_load, (PluginContext(self, info),), {}, LOAD_TIMEOUT
                )
                if not ok:
                    self._fail(info, f"on_load 失败: {result}")
                    self._remove_vendor(info)
                    return
            info.on_unload = getattr(module, "on_unload", None)
            info.on_settings_changed = getattr(module, "on_settings_changed", None)
            info.status = "loaded"
            info.reason = ""
            logger.info(
                "plugin %s v%s 已加载 (%s)",
                info.id,
                info.version,
                info.dir,
            )
        except BaseException as e:
            logger.exception("plugin %s 加载异常", info.id)
            self._fail(info, f"{type(e).__name__}: {e}")
            self._remove_vendor(info)

    def _fail(self, info: PluginInfo, reason: str):
        info.status = "failed"
        info.reason = reason
        info.clear_registry()
        logger.warning("plugin %s 跳过: %s", info.id, reason)

    def _add_vendor(self, info: PluginInfo):
        """vendor/ 目录追加到 sys.path 尾部（主程序依赖优先，禁用时移除）"""
        vendor = info.dir / "vendor"
        if vendor.is_dir():
            path = str(vendor)
            if path not in sys.path:
                sys.path.append(path)
                info.vendor_path = path

    def _remove_vendor(self, info: PluginInfo):
        if info.vendor_path and info.vendor_path in sys.path:
            try:
                sys.path.remove(info.vendor_path)
            except ValueError:
                pass
        info.vendor_path = None

    def _missing_deps(self, info: PluginInfo):
        """依赖三层策略第 2 层：find_spec 检测顶层包名，缺失即跳过"""
        missing = []
        for dep in info.dependencies:
            top = re.split(r"[\[<>=!; ]", dep)[0].strip().replace("-", "_")
            if not top:
                continue
            try:
                if importlib.util.find_spec(top) is None:
                    missing.append(top)
            except (ImportError, ValueError):
                missing.append(top)
        return missing

    # --- 隔离：统一回调守护 ---

    def _invoke(self, pid, fn, args, kwargs, timeout):
        """在独立线程执行插件回调；超时/异常（含 SystemExit）→ 熔断禁用该插件"""
        with self._lock:
            info = self._plugins.get(pid)
            if info is None or info.status not in ("loaded", "loading"):
                return False, "plugin_disabled"
        q = queue.Queue()

        def run():
            try:
                q.put((True, fn(*args, **kwargs)))
            except BaseException as e:
                q.put((False, f"{type(e).__name__}: {e}\n{traceback.format_exc()}"))

        t = threading.Thread(target=run, name=f"plugin-{pid}", daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            self._disable(pid, "timeout", f"回调超时 {timeout}s，已熔断禁用")
            return False, "handler_timeout"
        ok, val = q.get()
        if not ok:
            self._disable(pid, "exception", str(val).splitlines()[-1][:200])
            logger.error("plugin %s 回调异常（已熔断禁用）:\n%s", pid, val)
            return False, val
        return True, val

    def _disable(self, pid: str, reason: str, detail: str = ""):
        """运行期熔断：清空注册表实现逻辑注销（会话内不恢复，重启再试）"""
        with self._lock:
            info = self._plugins.get(pid)
            if info is None:
                return
            info.status = "disabled"
            info.reason = reason
            info.clear_registry()
        logger.warning("plugin %s 已禁用 (%s): %s", pid, reason, detail or reason)

    # --- 状态持久化（data_dir/plugins_state.json，原子写） ---

    def _settings_path(self, pid: str) -> Path:
        """插件设置文件路径（config_dir/plugins/<id>/settings.json，随用户配置）"""
        return self.cfg.config_dir / "plugins" / pid / "settings.json"

    def _migrate_settings_location(self):
        """旧位置 data_dir/plugins/<id>/settings.json 迁移到 config_dir"""
        old_root = self.cfg.data_dir / "plugins"
        try:
            entries = list(old_root.iterdir())
        except OSError:
            return
        for d in entries:
            if not d.is_dir():
                continue
            old = d / "settings.json"
            if not old.exists():
                continue
            target = self._settings_path(d.name)
            try:
                if not target.exists():
                    self._write_json(target, old.read_text(encoding="utf-8"))
                old.unlink()
            except OSError as e:
                logger.warning("plugin %s 设置迁移失败: %s", d.name, e)
                continue
            try:
                if not any(d.iterdir()):
                    d.rmdir()
            except OSError:
                pass

    @staticmethod
    def _write_json(path: Path, payload: str):
        """原子写 JSON 文本（先写临时文件再 os.replace）"""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            prefix=".settings-", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _read_settings_file(self, pid: str) -> dict:
        """读取单插件设置文件（缺失/损坏返回空 dict）"""
        path = self._settings_path(pid)
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    return {str(k): v for k, v in raw.items()}
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("plugin %s 设置读取失败: %s", pid, e)
        return {}

    def _load_state(self):
        legacy = {}
        try:
            if self.state_path.exists():
                with open(self.state_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    self._state["disabled"] = [
                        str(x) for x in raw.get("disabled", []) if isinstance(x, str)
                    ]
                    settings = raw.get("settings")
                    if isinstance(settings, dict):
                        legacy = {
                            str(k): v
                            for k, v in settings.items()
                            if isinstance(v, dict)
                        }
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("plugins_state 读取失败: %s", e)
        if legacy:
            self._migrate_legacy_settings(legacy)

    def _migrate_legacy_settings(self, legacy: dict):
        """旧版 plugins_state.json 内嵌设置迁移到 plugins/<id>/settings.json"""
        for pid, data in legacy.items():
            path = self._settings_path(pid)
            if path.exists():
                continue
            try:
                self._write_json(path, json.dumps(data, ensure_ascii=False, indent=2))
            except OSError as e:
                logger.warning("plugin %s 设置迁移失败: %s", pid, e)
        self._save_state()

    def _save_state(self):
        with self._lock:
            payload = json.dumps(self._state, ensure_ascii=False, indent=2)
            path = self.state_path
        try:
            self._write_json(path, payload)
        except OSError as e:
            logger.warning("plugins_state 保存失败: %s", e)

    # --- 启用/禁用 ---

    def is_enabled(self, pid: str) -> bool:
        with self._lock:
            info = self._plugins.get(pid)
            return bool(info and info.status == "loaded")

    def set_enabled(self, pid: str, enabled: bool) -> dict:
        """切换插件启用状态；禁用立即生效，启用需重启加载"""
        with self._lock:
            info = self._plugins.get(pid)
            if info is None:
                return {"ok": False, "error": "not_found"}
            disabled = self._state.setdefault("disabled", [])
            if enabled:
                if pid in disabled:
                    disabled.remove(pid)
                self._save_state()
                return {
                    "ok": True,
                    "enabled": info.status == "loaded",
                    "restart": info.status != "loaded",
                }
            if pid not in disabled:
                disabled.append(pid)
            self._save_state()
            if info.status == "loaded":
                info.status = "disabled"
                info.reason = "user_disabled"
                info.clear_registry()
                self._remove_vendor(info)
            return {"ok": True, "enabled": False, "restart": False}

    def list_info(self) -> list:
        """设置页插件列表（manifest 元信息 + 状态 + 权限清单）"""
        with self._lock:
            out = []
            for p in sorted(self._plugins.values(), key=lambda x: x.id):
                out.append(
                    {
                        "id": p.id,
                        "name": p.name,
                        "version": p.version,
                        "author": p.author,
                        "description": p.description,
                        "repo": p.repo,
                        "permissions": sorted(p.permissions),
                        "status": p.status,
                        "reason": p.reason,
                        "enabled": p.status == "loaded",
                        "restart": p.status == "disabled"
                        and p.id not in self._state.get("disabled", []),
                    }
                )
            return out

    # --- 插件设置读写 ---

    def get_settings(self, pid: str) -> dict:
        if not _ID_RE.match(str(pid)):
            return {}
        with self._lock:
            if pid not in self._settings:
                self._settings[pid] = self._read_settings_file(pid)
            return dict(self._settings[pid])

    def save_settings(self, pid: str, data: dict):
        """合并写入插件设置文件并触发 on_settings_changed（异常隔离）"""
        if not _ID_RE.match(str(pid)):
            return {"ok": False, "error": "invalid_id"}
        if not isinstance(data, dict):
            return {"ok": False, "error": "invalid_settings"}
        with self._lock:
            if pid not in self._settings:
                self._settings[pid] = self._read_settings_file(pid)
            self._settings[pid].update(data)
            payload = json.dumps(self._settings[pid], ensure_ascii=False, indent=2)
            path = self._settings_path(pid)
            info = self._plugins.get(pid)
            loaded = bool(info and info.status == "loaded")
            cb = info.on_settings_changed if loaded else None
        try:
            self._write_json(path, payload)
        except OSError as e:
            logger.warning("plugin %s 设置保存失败: %s", pid, e)
            return {"ok": False, "error": "save_failed"}
        if cb:
            ok, err = self._invoke(pid, cb, (dict(data),), {}, HANDLER_TIMEOUT)
            if not ok:
                return {"ok": False, "error": str(err)[:300]}
        return {"ok": True, "loaded": loaded}

    def open_plugins_dir(self) -> dict:
        """在系统文件管理器打开插件安装目录"""
        target = self.cfg.data_dir / "plugins"
        try:
            target.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(target))  # noqa: S606
            elif os.name == "darwin":
                import subprocess

                subprocess.Popen(["open", str(target)])
            else:
                import subprocess

                subprocess.Popen(["xdg-open", str(target)])
            return {"ok": True}
        except OSError as e:
            return {"ok": False, "error": str(e)}

    # --- 资产与注入 ---

    def _asset_version(self, info: PluginInfo) -> str:
        """资产缓存版本 = 插件版本 + 设置哈希（设置变化自动改 URL 防缓存）"""
        payload = json.dumps(
            self.get_settings(info.id),
            sort_keys=True,
            ensure_ascii=False,
        )
        digest = hashlib.md5(payload.encode("utf-8")).hexdigest()[:8]
        return f"{info.version}-{digest}"

    def asset_tags(self, window: str) -> str:
        """生成注入指定窗口的 <link>/<script> 标签（仅已启用插件）"""
        parts = []
        with self._lock:
            for p in sorted(self._plugins.values(), key=lambda x: x.id):
                if p.status != "loaded" or window not in p.windows:
                    continue
                slot = p.assets.get(window)
                if not slot:
                    continue
                ver = self._asset_version(p)
                for rel in slot.get("css", []):
                    parts.append(
                        f'<link rel="stylesheet" href="/plugins/{p.id}/{rel}?v={ver}">'
                    )
                for rel in slot.get("js", []):
                    parts.append(
                        f'<script defer src="/plugins/{p.id}/{rel}?v={ver}"></script>'
                    )
        return "\n".join(parts)

    def settings_sections(self) -> str:
        """设置窗口插件分组内注入的 section HTML 片段拼接"""
        with self._lock:
            return "\n".join(
                section
                for p in sorted(self._plugins.values(), key=lambda x: x.id)
                if p.status == "loaded"
                for section in p.sections
            )

    def resolve_asset(self, pid: str, relpath: str):
        """解析插件静态资产为 (绝对路径, MIME)；禁用/穿越/不存在返回 None

        以 `data/` 开头的路径解析到插件私有数据目录（data_dir/plugins_data/<id>/），
        其余路径解析到插件代码目录。
        """
        with self._lock:
            info = self._plugins.get(pid)
            if info is None or info.status != "loaded":
                return None
            base = info.dir.resolve()
        clean = relpath.replace("\\", "/").lstrip("/")
        if not clean or ".." in clean.split("/"):
            return None
        if clean.startswith("data/"):
            base = (self.cfg.data_dir / "plugins_data" / pid).resolve()
            clean = clean[5:]
            if not clean or ".." in clean.split("/"):
                return None
        target = (base / clean).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            return None
        return target, _MIME.get(target.suffix.lower())

    def custom_routes(self) -> list:
        """已启用插件注册的自定义路由 [(pid, rule, fn)]"""
        with self._lock:
            return [
                (p.id, rule, fn)
                for p in sorted(self._plugins.values(), key=lambda x: x.id)
                if p.status == "loaded"
                for rule, fn in p.routes
            ]

    def call_route(self, pid: str, fn, params: dict):
        """执行插件路由处理器（超时/异常熔断），返回 (ok, result)"""
        with self._lock:
            info = self._plugins.get(pid)
            if info is None or info.status != "loaded":
                return False, "plugin_disabled"
        return self._invoke(pid, fn, (dict(params),), {}, HANDLER_TIMEOUT)

    # --- js_api 分发 ---

    def call_main(self, pid: str, method: str, args: list):
        """主窗口 JsApi.plugin_call 分发；失败按 js_api 约定返回 {ok:false,...}"""
        return self._call_api(pid, method, args, "main_api")

    def call_settings(self, pid: str, method: str, args: list):
        """设置窗口 SettingsApi.plugin_call 分发"""
        return self._call_api(pid, method, args, "settings_api")

    def _call_api(self, pid, method, args, registry_name):
        with self._lock:
            info = self._plugins.get(pid)
            if info is None or info.status != "loaded":
                return {"ok": False, "error": "plugin_disabled"}
            fn = getattr(info, registry_name).get(method)
        if fn is None:
            return {"ok": False, "error": "method_not_found"}
        if not isinstance(args, (list, tuple)):
            args = [args]
        ok, val = self._invoke(pid, fn, tuple(args), {}, _API_TIMEOUT)
        if not ok:
            return {"ok": False, "error": str(val)[:300]}
        return val

    def call_button(self, pid: str, key: str) -> dict:
        """顶栏插件按钮点击分发（经 JsApi.plugin_button_click）"""
        with self._lock:
            info = self._plugins.get(pid)
            if info is None or info.status != "loaded":
                return {"ok": False, "error": "plugin_disabled"}
            fn = info.button_handler
        if fn is None:
            return {"ok": False, "error": "no_button_handler"}
        ok, val = self._invoke(pid, fn, (str(key),), {}, HANDLER_TIMEOUT)
        if not ok:
            return {"ok": False, "error": str(val)[:300]}
        return {"ok": True, "result": val}

    # --- 前端/窗口聚合数据 ---

    def startup_overrides(self) -> dict:
        """启动动画覆盖（按 id 序合并，后者覆盖前者）"""
        out = {}
        with self._lock:
            for p in sorted(self._plugins.values(), key=lambda x: x.id):
                if p.status == "loaded" and p.startup:
                    out.update(p.startup)
        return out

    def window_params(self) -> dict:
        """主窗口初始尺寸覆盖（width/height，空则由主程序配置决定）"""
        out = {}
        with self._lock:
            for p in sorted(self._plugins.values(), key=lambda x: x.id):
                if p.status == "loaded" and p.window:
                    out.update(p.window)
        return out

    def buttons_for_frontend(self) -> list:
        """已启用插件的顶栏按钮列表（icon 转为带版本号的资产 URL）"""
        out = []
        with self._lock:
            for p in sorted(self._plugins.values(), key=lambda x: x.id):
                if p.status != "loaded" or not p.buttons:
                    continue
                ver = self._asset_version(p)
                for b in p.buttons:
                    icon = b["icon"]
                    if icon:
                        icon = f"/plugins/{p.id}/{icon.lstrip('/')}?v={ver}"
                    out.append(
                        {
                            "plugin_id": p.id,
                            "key": b["key"],
                            "label": b["label"],
                            "icon": icon,
                            "order": b["order"],
                        }
                    )
        return out

    def button_constraints(self) -> dict:
        """核心顶栏按钮约束合并 {hide:[...], order:{...}}（按 id 序后者覆盖）"""
        hide = set()
        order = {}
        with self._lock:
            for p in sorted(self._plugins.values(), key=lambda x: x.id):
                if p.status != "loaded":
                    continue
                hide.update(p.button_constraints["hide"])
                order.update(p.button_constraints["order"])
        return {"hide": sorted(hide), "order": order}

    def init_fields(self) -> dict:
        """get_init_data 并入的插件字段（启动动画/按钮）"""
        startup = self.startup_overrides()
        return {
            "startup_video_src": startup.get("video_src", ""),
            "startup_bg_color": startup.get("bg_color", ""),
            "startup_media_duration_ms": int(startup.get("duration_ms") or 0),
            "startup_media_type": startup.get("media_type", ""),
            "plugin_buttons": self.buttons_for_frontend(),
            "plugin_button_constraints": self.button_constraints(),
        }

    def evaluate_js(self, code: str):
        """向主窗口推送 JS（失败仅告警）"""
        try:
            import webview

            if webview.windows:
                webview.windows[0].evaluate_js(code)
        except Exception as e:
            logger.warning("plugin evaluate_js failed: %s", e)


# 全局单例
_manager = None


def route_content_type(rule: str) -> str:
    """按插件路由规则的扩展名推断响应 Content-Type"""
    return _MIME.get(Path(rule.split("?")[0]).suffix.lower())


def get_plugin_manager() -> PluginManager:
    global _manager
    if _manager is None:
        _manager = PluginManager()
    return _manager
