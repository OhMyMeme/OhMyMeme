# pyright: basic

"""插件 worker 进程：加载插件、代理宿主能力、执行操作。"""

import argparse
import base64
import importlib
import inspect
import json
import logging
import os
import sys
import threading
import uuid
from pathlib import Path

from ohmymeme.core.imports import ImportResult
from ohmymeme.core.plugins.contracts import (
    ImportPluginContext,
    PluginCapabilities,
    PluginDescriptor,
)
from ohmymeme.core.plugins.manifest import ENTRY_POINT_GROUP
from ohmymeme.core.plugins.network_config import SYNC_CONFIGS, LanTransportConfig
from ohmymeme.core.plugins.policy import (
    PluginPolicyError,
    TemporaryWorkspace,
    redact,
)
from ohmymeme.core.plugins.runtime import protocol
from ohmymeme.core.plugins.runtime.channel import RpcChannel, RpcError

logger = logging.getLogger(__name__)

QUERY_METHODS = ("inspect", "get_progress")
SYNC_METHODS = (
    "connect",
    "upload_file",
    "download_file",
    "list_files",
    "ensure_remote_dir",
    "file_exists",
    "delete_file",
    "test_connection",
    "clear_directory_cache",
)
_PATH_ARGUMENTS = {"upload_file": (0,), "download_file": (1,)}


# LAN listener 注册由宿主协调器持有 worker 进程，插件侧无需回调
def _ignore_socket(_socket):
    return None


_OPERATION_TARGETS = {
    "import": "import_media",
    "list": "list_stickers",
}


# 校验操作结果可 JSON 序列化
def _jsonable(value):
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise ValueError("operation result is not serializable") from error
    return value


# 校验临时目录内相对路径
class _WorkerSettings:
    def __init__(self, worker, op_id, values):
        self._worker = worker
        self._op_id = op_id
        self._values = values

    # 读取宿主注入的配置值
    def get(self, key, default=None):
        return self._values.get(key, default)

    # 写入前由宿主校验并持久化
    def set(self, key, value):
        self._worker._channel.call(
            "config.set",
            {"op_id": self._op_id, "key": key, "value": value},
            timeout=10.0,
        )
        self._values[key] = value


class _WorkerSecrets:
    def __init__(self, values):
        self._values = values

    # 密钥只读，按操作注入
    def get(self, key):
        return self._values.get(key)


class WorkerOperation:
    def __init__(self, worker, op_id, params):
        self._worker = worker
        self._op_id = op_id
        self._workspace = TemporaryWorkspace(params["workspace"])
        self._settings = _WorkerSettings(
            worker, op_id, dict(params.get("config") or {})
        )
        self._secrets = _WorkerSecrets(dict(params.get("secrets") or {}))
        self._redaction = set()
        self._closed = False

    @property
    def temporary(self):
        return self._workspace

    @property
    def settings(self):
        return self._settings

    @property
    def secrets(self):
        return self._secrets

    # 能力声明由宿主随注册表冻结，worker 只做本地复核
    def require(self, capability):
        if self._closed:
            raise PluginPolicyError("operation scope is closed")
        if capability not in self._worker._capabilities:
            raise PluginPolicyError(f"undeclared capability {capability!r}")

    # 统一在 worker 出口脱敏
    def _serialize(self, value):
        return redact(value, (*self._secrets._values.values(), *self._redaction))

    serialize_descriptor = _serialize
    serialize_progress = _serialize
    serialize_error = _serialize
    serialize_log = _serialize

    # 记录运行期派生密钥，只用于脱敏
    def protect_secret(self, value):
        if isinstance(value, str) and value:
            self._redaction.add(value)

    # 发送进度通知
    def emit_progress(self, value):
        self._worker._notify("progress", self._op_id, self._serialize(value))

    # 发送日志通知
    def emit_log(self, value):
        self._worker._notify("log", self._op_id, self._serialize(value))

    emit_error = emit_log
    emit_descriptor = emit_log


class WorkerSink:
    def __init__(self, worker, op_id):
        self._worker = worker
        self._op_id = op_id

    # 把 ImportPath 列表投影为 JSON 请求
    @staticmethod
    def _requests(items):
        return [{"path": str(item.path), "name": item.original_name} for item in items]

    # 调用宿主批量导入
    def import_batch(self, requests, cancelled=None):
        if cancelled is not None and cancelled():
            return ImportResult((), 0)
        result = self._worker._channel.call(
            "sink.import_batch",
            {"op_id": self._op_id, "requests": self._requests(requests)},
            timeout=600.0,
        )
        return ImportResult(
            tuple(result.get("ids") or ()), int(result.get("rejected") or 0)
        )

    # 调用宿主单文件导入
    def import_path(self, request, cancelled=None):
        if cancelled is not None and cancelled():
            return ImportResult((), 0)
        result = self._worker._channel.call(
            "sink.import_path",
            {"op_id": self._op_id, "request": self._requests((request,))[0]},
            timeout=600.0,
        )
        return ImportResult(
            tuple(result.get("ids") or ()), int(result.get("rejected") or 0)
        )

    # 字节导入暂不在 worker 边界提供
    def import_bytes(self, request, cancelled=None):
        raise RpcError(protocol.ERROR_UNSUPPORTED, "import_bytes unavailable")


class WorkerResources:
    def __init__(self, worker, op_id):
        self._worker = worker
        self._op_id = op_id

    # 登记插件自建子进程供宿主追踪
    def register_process(self, process):
        pid = getattr(process, "pid", None)
        if isinstance(pid, int):
            self._worker._channel.notify(
                "process.registered", {"op_id": self._op_id, "pid": pid}
            )
        return process

    # 请求宿主准备微信 helper 操作内副本
    def wechat_helper(self):
        result = self._worker._channel.call(
            "helper.wechat", {"op_id": self._op_id}, timeout=120.0
        )
        return tuple(result)


class PluginWorker:
    def __init__(self, plugin_id, token):
        self._plugin_id = plugin_id
        self._token = token
        self._channel = None
        self._instance = None
        self._descriptor = None
        self._capabilities = frozenset()
        self._cancel = threading.Event()
        self._stop = threading.Event()
        self._op_lock = threading.Lock()
        self._op_thread = None
        self._sync_sessions = {}
        self._lan_sessions = {}
        self._ui_actions = frozenset()

    def attach(self, channel):
        self._channel = channel

    # 处理宿主发来的固定方法请求
    def handle_request(self, method, params):
        if method == "ping":
            return {"pong": True}
        if method == "plugin.query":
            return self._handle_query(params)
        if method == "operation.start":
            return self._handle_operation_start(params)
        if method == "operation.cancel":
            self._handle_operation_cancel(params)
            return {"ok": True}
        if method == "ui.action":
            return self._handle_ui_action(params)
        if method == "sync.open":
            return self._handle_sync_open(params)
        if method == "sync.call":
            return self._handle_sync_call(params)
        if method == "sync.close":
            return self._handle_sync_close(params)
        if method == "lan.open":
            return self._handle_lan_open(params)
        if method.startswith("lan."):
            return self._handle_lan_call(method, params)
        if method == "shutdown":
            self._stop.set()
            return {"ok": True}
        raise RpcError(protocol.RPC_METHOD_NOT_FOUND, "unknown method")

    # 通道关闭等同于宿主退出
    def on_channel_closed(self, _reason):
        self._stop.set()

    # 启动握手、加载插件、等待停止
    def run(self):
        welcome = self._channel.call(
            "hello",
            {
                "protocol_version": protocol.PROTOCOL_VERSION,
                "plugin_id": self._plugin_id,
                "token": self._token,
                "pid": os.getpid(),
                "python": "%d.%d" % sys.version_info[:2],
            },
            timeout=15.0,
        )
        if not isinstance(welcome, dict) or not welcome.get("accepted"):
            raise RuntimeError(
                "handshake rejected: %s" % (welcome or {}).get("reason", "")
            )
        plugin = welcome.get("plugin") or {}
        failure = ""
        try:
            self._load_plugin(plugin)
        except Exception as error:
            failure = "%s: %s" % (type(error).__name__, error)
            logger.exception("plugin load failed")
        self._channel.call(
            "ready",
            {"ok": not failure, "error": failure},
            timeout=10.0,
        )
        if failure:
            return 1
        self._stop.wait()
        self._shutdown()
        return 0

    # 从种子目录加载插件并校验身份
    def _load_plugin(self, plugin):
        package_dir = plugin["package_dir"]
        entry = plugin["entry"]
        module_name, _, attribute = entry.partition(":")
        if not module_name or attribute != "create_plugin":
            raise RuntimeError("invalid plugin entry")
        sys.path.insert(0, package_dir)
        module = importlib.import_module(module_name)
        factory = getattr(module, attribute, None)
        if not callable(factory):
            raise RuntimeError("plugin factory missing")
        instance = factory()
        provider_id = getattr(instance, "provider_id", None)
        api_version = getattr(instance, "api_version", None)
        if provider_id != plugin["id"] or type(api_version) is not int:
            raise RuntimeError("plugin identity mismatch")
        self._instance = instance
        self._capabilities = frozenset(plugin.get("capabilities") or ())
        self._descriptor = PluginDescriptor(
            provider_id,
            api_version,
            plugin.get("package_root", module_name),
            ENTRY_POINT_GROUP,
            provider_id,
            entry,
            PluginCapabilities(tuple(plugin.get("capabilities") or ())),
        )
        try:
            from ohmymeme.core.plugins.runtime.ui_injection import load_ui_actions

            self._ui_actions = load_ui_actions(package_dir)
        except Exception:
            # 无效 ui.json 不影响插件运行，只让 UI 动作不可用
            self._ui_actions = frozenset()

    # 允许的同步查询：固定方法名 + 按签名注入宿主回调
    def _handle_query(self, params):
        name = params.get("method")
        if name not in QUERY_METHODS:
            raise RpcError(protocol.RPC_METHOD_NOT_FOUND, "unknown query")
        handler = getattr(self._instance, name, None)
        if not callable(handler):
            raise RpcError(protocol.RPC_METHOD_NOT_FOUND, "query unavailable")
        values = dict(params.get("params") or {})
        signature = inspect.signature(handler)
        kwargs = {
            key: value for key, value in values.items() if key in signature.parameters
        }
        if "nickname_lookup" in signature.parameters:
            kwargs["nickname_lookup"] = self._nickname_lookup(params.get("query_id"))
        return _jsonable(handler(**kwargs))

    # 查询宿主昵称缓存
    def _nickname_lookup(self, query_id):
        def lookup(qq):
            return self._channel.call(
                "nickname.lookup",
                {"qq": str(qq), "query_id": query_id},
                timeout=30.0,
            )

        return lookup

    # 受理一次操作并启动执行线程
    def _handle_operation_start(self, params):
        op_id = params.get("op_id")
        kind = params.get("kind")
        target_name = _OPERATION_TARGETS.get(kind)
        if not isinstance(op_id, str) or target_name is None:
            raise RpcError(protocol.RPC_INVALID_PARAMS, "invalid operation")
        with self._op_lock:
            if self._op_thread is not None and self._op_thread.is_alive():
                return {"accepted": False, "reason": protocol.ERROR_OPERATION_BUSY}
            target = getattr(self._instance, target_name, None)
            if not callable(target):
                return {"accepted": False, "reason": protocol.ERROR_UNSUPPORTED}
            self._cancel.clear()
            operation = WorkerOperation(self, op_id, params)
            context = ImportPluginContext(
                self._descriptor,
                WorkerSink(self, op_id),
                lambda value: self._notify_progress(op_id, value),
                self._cancel.is_set,
                operation=operation,
                request=dict(params.get("request") or {}),
                resources=WorkerResources(self, op_id),
            )
            start = getattr(self._instance, "start", None)
            started = start(context) if callable(start) else True
            if not started:
                self._finish_instance()
                return {"accepted": False, "reason": protocol.ERROR_OPERATION_BUSY}
            get_progress = getattr(self._instance, "get_progress", None)
            snapshot = (
                operation.serialize_progress(get_progress())
                if callable(get_progress)
                else {}
            )
            self._op_thread = threading.Thread(
                target=self._run_operation,
                args=(op_id, target, context),
                name="plugin-op",
                daemon=True,
            )
            self._op_thread.start()
        return {"accepted": True, "progress": _jsonable(snapshot)}

    # 取消当前操作：置取消标志并调用插件 stop
    def _handle_operation_cancel(self, params):
        self._cancel.set()
        stop = getattr(self._instance, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                logger.exception("plugin stop failed")

    # 执行插件声明过的 UI 动作（allowlist 来自 ui.json）
    def _handle_ui_action(self, params):
        name = params.get("name")
        if name not in self._ui_actions:
            raise RpcError(protocol.ERROR_UNSUPPORTED, "unknown ui action")
        handler = getattr(self._instance, "handle_ui_action", None)
        if not callable(handler):
            raise RpcError(protocol.ERROR_UNSUPPORTED, "ui action unavailable")
        try:
            return _jsonable(handler(str(name), dict(params.get("payload") or {})))
        except Exception as error:
            raise RpcError(
                type(error).__name__,
                str(error),
                {"exception": type(error).__name__},
            ) from None

    # 打开同步 backend 会话
    def _handle_sync_open(self, params):
        session_id = params.get("session_id")
        provider_id = params.get("provider_id")
        if not isinstance(session_id, str) or provider_id != self._plugin_id:
            raise RpcError(protocol.RPC_INVALID_PARAMS, "invalid sync session")
        if provider_id not in SYNC_CONFIGS:
            raise RpcError(protocol.ERROR_UNSUPPORTED, "not a sync provider")
        record = SYNC_CONFIGS[provider_id](**dict(params.get("config") or {}))
        secrets = _WorkerSecrets(dict(params.get("secrets") or {}))
        create_backend = getattr(self._instance, "create_backend", None)
        if not callable(create_backend):
            raise RpcError(protocol.ERROR_UNSUPPORTED, "backend unavailable")
        with self._op_lock:
            self._sync_sessions[session_id] = create_backend(record, secrets)
        return {"ok": True}

    # 在会话内调用 backend 固定方法
    def _handle_sync_call(self, params):
        session_id = params.get("session_id")
        name = params.get("method")
        if name not in SYNC_METHODS:
            raise RpcError(protocol.RPC_METHOD_NOT_FOUND, "unknown backend method")
        with self._op_lock:
            backend = self._sync_sessions.get(session_id)
        if backend is None:
            raise RpcError(protocol.ERROR_OPERATION_UNKNOWN, "unknown sync session")
        method = getattr(backend, name, None)
        if not callable(method):
            raise RpcError(protocol.ERROR_UNSUPPORTED, "method unavailable")
        arguments = list(params.get("args") or ())
        for index in _PATH_ARGUMENTS.get(name, ()):
            if index < len(arguments):
                arguments[index] = Path(arguments[index])
        try:
            return _jsonable(method(*arguments))
        except Exception as error:
            raise RpcError(
                type(error).__name__,
                str(error),
                {"exception": type(error).__name__},
            ) from None

    # 关闭同步会话并回收 backend
    def _handle_sync_close(self, params):
        session_id = params.get("session_id")
        with self._op_lock:
            backend = self._sync_sessions.pop(session_id, None)
        if backend is not None:
            close = getattr(backend, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logger.exception("sync backend close failed")
        return {"ok": True}

    # 打开 LAN transport 会话（socket/发现都留在 worker）
    def _handle_lan_open(self, params):
        session_id = params.get("session_id")
        if not isinstance(session_id, str):
            raise RpcError(protocol.RPC_INVALID_PARAMS, "invalid lan session")
        create_transport = getattr(self._instance, "create_transport", None)
        if not callable(create_transport):
            raise RpcError(protocol.ERROR_UNSUPPORTED, "transport unavailable")
        config = LanTransportConfig(**dict(params.get("config") or {}))
        try:
            transport = create_transport(config)
            transport.open(_ignore_socket)
        except Exception as error:
            raise self._lan_error(error)
        with self._op_lock:
            self._lan_sessions[session_id] = {
                "transport": transport,
                "connections": {},
            }
        return {
            "port": transport.port,
            "pktinfo": bool(getattr(transport, "pktinfo", False)),
        }

    # LAN 会话内固定方法分发
    def _handle_lan_call(self, method, params):
        if method == "lan.get_ip":
            return {"ip": str(self._instance.get_lan_ip())}
        session_id = params.get("session_id")
        with self._op_lock:
            session = self._lan_sessions.get(session_id)
        if session is None:
            raise RpcError(protocol.ERROR_OPERATION_UNKNOWN, "unknown lan session")
        if method == "lan.close":
            with self._op_lock:
                self._lan_sessions.pop(session_id, None)
            self._close_lan_session(session)
            return {"ok": True}
        if method == "lan.receive_discovery":
            try:
                discovery = session["transport"].receive_discovery()
            except Exception as error:
                raise self._lan_error(error)
            if discovery is None:
                return {"discovery": None}
            address, source = discovery
            return {
                "discovery": {
                    "address": [address[0], address[1]],
                    "source": None if source is None else list(source),
                }
            }
        if method == "lan.send_discovery":
            data = base64.b64decode(str(params.get("data") or ""))
            address = tuple(params.get("address") or ())
            source = params.get("source")
            try:
                session["transport"].send_discovery(
                    data, address, None if source is None else tuple(source)
                )
            except Exception as error:
                raise self._lan_error(error)
            return {"ok": True}
        if method == "lan.accept":
            try:
                connection, address = session["transport"].accept()
            except Exception as error:
                raise self._lan_error(error)
            connection_id = uuid.uuid4().hex
            session["connections"][connection_id] = connection
            return {
                "connection_id": connection_id,
                "address": [address[0], address[1]],
            }
        connection_id = params.get("connection_id")
        connection = session["connections"].get(connection_id)
        if connection is None:
            raise RpcError(protocol.ERROR_OPERATION_UNKNOWN, "unknown connection")
        if method == "lan.connection.receive":
            try:
                data = connection.receive_bytes(int(params.get("size") or 0))
            except Exception as error:
                raise self._lan_error(error)
            return {"data": base64.b64encode(data).decode("ascii")}
        if method == "lan.connection.send":
            data = base64.b64decode(str(params.get("data") or ""))
            try:
                connection.send_bytes(data)
            except Exception as error:
                raise self._lan_error(error)
            return {"ok": True}
        if method == "lan.connection.settimeout":
            try:
                connection.settimeout(params.get("timeout"))
            except Exception as error:
                raise self._lan_error(error)
            return {"ok": True}
        if method == "lan.connection.close":
            session["connections"].pop(connection_id, None)
            try:
                connection.close()
            except OSError:
                pass
            return {"ok": True}
        raise RpcError(protocol.RPC_METHOD_NOT_FOUND, "unknown lan method")

    # 统一把 LAN 异常投影为 RPC 错误
    def _lan_error(self, error):
        return RpcError(
            type(error).__name__,
            str(error),
            {"exception": type(error).__name__},
        )

    # 回收会话内连接与 transport
    def _close_lan_session(self, session):
        for connection in list(session.get("connections", {}).values()):
            try:
                connection.close()
            except OSError:
                pass
        session["connections"].clear()
        transport = session.get("transport")
        if transport is not None:
            try:
                transport.close()
            except OSError:
                pass

    # 进度通知带 worker 侧脱敏后的值
    def _notify_progress(self, op_id, value):
        self._notify("progress", op_id, value)

    # 统一发送通知
    def _notify(self, method, op_id, value):
        if self._channel is not None:
            self._channel.notify(method, {"op_id": op_id, "value": value})

    # 调用插件收尾钩子
    def _finish_instance(self):
        finish = getattr(self._instance, "finish", None)
        if callable(finish):
            try:
                finish()
            except Exception:
                logger.exception("plugin finish failed")

    # 在操作线程内执行并回报结果
    def _run_operation(self, op_id, target, context):
        outcome = {}
        try:
            result = target(context)
            outcome = {"ok": True, "result": _jsonable(result)}
        except Exception as error:
            logger.exception("operation failed")
            outcome = {"ok": False, "error": str(error)}
        finally:
            self._finish_instance()
        if self._channel is not None:
            self._channel.notify("operation.finished", {"op_id": op_id, **outcome})

    # 停止时先取消并等待操作线程退出
    def _shutdown(self):
        self._cancel.set()
        stop = getattr(self._instance, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                pass
        with self._op_lock:
            sessions = list(self._sync_sessions.values())
            self._sync_sessions.clear()
            lan_sessions = list(self._lan_sessions.values())
            self._lan_sessions.clear()
        for backend in sessions:
            close = getattr(backend, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logger.exception("sync backend close failed")
        for session in lan_sessions:
            self._close_lan_session(session)
        thread = self._op_thread
        if thread is not None:
            thread.join(timeout=10.0)
            if thread.is_alive():
                logger.error("operation thread did not exit")
                os._exit(1)


# worker 进程入口
def main(argv=None):
    parser = argparse.ArgumentParser(prog="ohmymeme-plugin-worker")
    parser.add_argument("--plugin-worker", action="store_true")
    parser.add_argument("--plugin-id", required=True)
    parser.add_argument("--token", default="")
    parser.add_argument("--debug", action="store_true")
    arguments = parser.parse_args(argv)
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.DEBUG if arguments.debug else logging.INFO,
        format="[worker %(levelname)s] %(name)s: %(message)s",
    )
    worker = PluginWorker(arguments.plugin_id, arguments.token)
    channel = RpcChannel(
        sys.stdin.buffer,
        sys.stdout.buffer,
        on_request=worker.handle_request,
        on_close=worker.on_channel_closed,
        name="worker-" + arguments.plugin_id,
        max_workers=16,
    )
    worker.attach(channel)
    channel.start()
    try:
        return worker.run()
    except Exception:
        logger.exception("worker failed")
        return 1
    finally:
        channel.close("worker exit")
