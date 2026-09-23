# pyright: basic

"""宿主侧插件 runtime：worker 监管、RPC 调用与操作生命周期。"""

import base64
import logging
import os
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

from ohmymeme.core.plugins.runtime import process_tree, protocol, seeding
from ohmymeme.core.plugins.runtime.channel import (
    ChannelClosed,
    RpcChannel,
    RpcError,
)

logger = logging.getLogger(__name__)

HANDSHAKE_TIMEOUT = 30.0
OPERATION_START_TIMEOUT = 30.0
REQUEST_TIMEOUT = 30.0
PING_INTERVAL = 5.0
PING_TIMEOUT = 10.0
PING_FAILURE_LIMIT = 2
RESTART_WINDOW = 600.0
RESTART_LIMIT = 3
RESTART_BACKOFF = 4.0
IDLE_TTL = 300.0
MAX_WORKERS = 8


class PluginRuntimeError(RuntimeError):
    def __init__(self, reason, message=""):
        text = "%s: %s" % (reason, message) if message else reason
        super().__init__(text)
        self.reason = reason


class RuntimeOperation:
    def __init__(self, manager, worker, op_id, kind, callbacks):
        self._manager = manager
        self.worker = worker
        self.op_id = op_id
        self.kind = kind
        self.done = threading.Event()
        self.outcome = None
        self.initial_progress = None
        self.cancelled = False
        self.on_progress = callbacks.get("progress")
        self.on_log = callbacks.get("log")
        self.sink_batch = callbacks.get("sink_batch")
        self.sink_path = callbacks.get("sink_path")
        self.config_set = callbacks.get("config_set")
        self.helper_wechat = callbacks.get("helper_wechat")

    # 等待操作结束并返回结果
    def wait(self, timeout=None):
        self.done.wait(timeout)
        if not self.done.is_set():
            return None
        return self.outcome

    # 请求取消当前操作
    def cancel(self):
        self.cancelled = True
        self._manager.cancel_operation(self)


class RuntimeSyncSession:
    """宿主侧同步会话句柄：backend 方法经固定 RPC 转发到 worker。"""

    def __init__(self, worker, session_id):
        self._worker = worker
        self.session_id = session_id

    # 调用 backend 方法并保留异常类别语义
    def call(self, method, args=(), timeout=None):
        channel = self._worker.channel
        try:
            return channel.call(
                "sync.call",
                {
                    "session_id": self.session_id,
                    "method": method,
                    "args": list(args),
                },
                timeout=timeout,
            )
        except RpcError as error:
            data = error.data if isinstance(error.data, dict) else {}
            name = data.get("exception")
            if name == "NotImplementedError":
                raise NotImplementedError(error.message) from None
            if name == "SyncError":
                from ohmymeme.core.plugins.network_config import SyncError

                raise SyncError(error.message) from None
            if name == "OSError":
                raise OSError(error.message) from None
            raise

    # 关闭会话并回收 worker 内 backend
    def close(self):
        channel = self._worker.channel
        if channel is None or channel.is_closed():
            return
        try:
            channel.call("sync.close", {"session_id": self.session_id}, timeout=15.0)
        except (ChannelClosed, RpcError):
            pass


class RuntimeLanConnection:
    """宿主侧 LAN 连接代理：字节读写经 RPC 转到 worker socket。"""

    def __init__(self, worker, session_id, connection_id, address):
        self._worker = worker
        self.session_id = session_id
        self.connection_id = connection_id
        self.address = address
        self._closed = False

    # 统一转发并保留超时/OS 异常类别
    def _call(self, method, params=None, timeout=None):
        payload = {
            "session_id": self.session_id,
            "connection_id": self.connection_id,
        }
        payload.update(params or {})
        try:
            return self._worker.channel.call(method, payload, timeout=timeout)
        except RpcError as error:
            data = error.data if isinstance(error.data, dict) else {}
            name = data.get("exception")
            if name in ("TimeoutError", "timeout"):
                raise socket.timeout(error.message) from None
            if name in (
                "OSError",
                "BrokenPipeError",
                "ConnectionError",
                "ConnectionResetError",
                "ConnectionAbortedError",
            ) or error.code in (protocol.ERROR_OPERATION_UNKNOWN, "channel_closed"):
                raise OSError(error.message) from None
            raise

    # 读取字节，超时抛 socket.timeout
    def receive_bytes(self, size):
        if self._closed:
            raise OSError("connection closed")
        result = self._call("lan.connection.receive", {"size": int(size)}, timeout=None)
        return base64.b64decode(result.get("data") or "")

    # 写入字节
    def send_bytes(self, data):
        if self._closed:
            raise OSError("connection closed")
        self._call(
            "lan.connection.send",
            {"data": base64.b64encode(bytes(data)).decode("ascii")},
            timeout=None,
        )

    def settimeout(self, timeout):
        self._call("lan.connection.settimeout", {"timeout": timeout}, timeout=15.0)

    # 幂等关闭；worker 失联时静默
    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._call("lan.connection.close", timeout=15.0)
        except (ChannelClosed, RpcError, OSError):
            pass


class RuntimeLanTransport:
    """宿主侧 LAN transport 代理：发现/accept/close 经 RPC 转发。"""

    def __init__(self, worker, session_id, port, pktinfo):
        self._worker = worker
        self.session_id = session_id
        self.port = port
        self.udp = None
        self.tcp = None
        self.pktinfo = pktinfo
        self._closed = False

    def _call(self, method, params=None, timeout=None):
        payload = {"session_id": self.session_id}
        payload.update(params or {})
        try:
            return self._worker.channel.call(method, payload, timeout=timeout)
        except RpcError as error:
            data = error.data if isinstance(error.data, dict) else {}
            name = data.get("exception")
            if name in ("TimeoutError", "timeout"):
                raise socket.timeout(error.message) from None
            if name in (
                "OSError",
                "BrokenPipeError",
                "ConnectionError",
                "ConnectionResetError",
                "ConnectionAbortedError",
            ) or error.code in (protocol.ERROR_OPERATION_UNKNOWN, "channel_closed"):
                raise OSError(error.message) from None
            raise

    # worker 已完成 bind；宿主协调器按 worker 进程追踪
    def open(self, _register_socket=None):
        return None

    # 接收一次发现报文，超时抛 socket.timeout
    def receive_discovery(self):
        result = self._call("lan.receive_discovery", timeout=None)
        discovery = result.get("discovery")
        if discovery is None:
            return None
        address = tuple(discovery.get("address") or ())
        source = discovery.get("source")
        return address, None if source is None else tuple(source)

    # 回复发现报文
    def send_discovery(self, data, address, source):
        self._call(
            "lan.send_discovery",
            {
                "data": base64.b64encode(bytes(data)).decode("ascii"),
                "address": list(address or ()),
                "source": None if source is None else list(source),
            },
            timeout=None,
        )

    # 接受一个连接，超时抛 socket.timeout
    def accept(self):
        result = self._call("lan.accept", timeout=None)
        address = tuple(result.get("address") or ())
        connection = RuntimeLanConnection(
            self._worker,
            self.session_id,
            result.get("connection_id", ""),
            address,
        )
        return connection, address

    # 幂等关闭整个 LAN 会话
    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._call("lan.close", timeout=15.0)
        except (ChannelClosed, RpcError, OSError):
            pass


class WorkerHandle:
    def __init__(self, plugin_id, spec, token):
        self.plugin_id = plugin_id
        self.spec = spec
        self.token = token
        self.process = None
        self.channel = None
        self.ready = threading.Event()
        self.ready_ok = False
        self.ready_error = ""
        self.closed = False
        self.stopping = False
        self.started_at = 0.0
        self.last_activity = time.monotonic()
        self.ping_failures = 0
        self.pinging = False
        self.operations = {}
        self.lock = threading.RLock()


class PluginRuntimeManager:
    def __init__(self, data_dir, resolver=None, spawn=None):
        self._data_dir = Path(data_dir)
        self._resolver = resolver or self._default_resolver
        self._spawn = spawn or process_tree.spawn_worker
        self._workers = {}
        self._worker_locks = {}
        self._operations = {}
        self._queries = {}
        self._quarantine = {}
        self._crashes = {}
        self._seeded = False
        self._lock = threading.RLock()
        self._closed = False
        self._heartbeat = threading.Thread(
            target=self._heartbeat_loop, name="plugin-runtime-heartbeat", daemon=True
        )
        self._heartbeat.start()

    # 默认从用户插件目录解析活动版本；缺失时先种子官方九包
    def _default_resolver(self, plugin_id):
        try:
            return seeding.resolve_plugin(self._data_dir, plugin_id)
        except seeding.PluginSeedError:
            with self._lock:
                if not self._seeded:
                    seeding.seed_official_plugins(self._data_dir)
                    self._seeded = True
            return seeding.resolve_plugin(self._data_dir, plugin_id)

    # 确保插件 worker 已就绪，必要时启动或重启
    def ensure(self, plugin_id):
        with self._lock:
            if self._closed:
                raise PluginRuntimeError("runtime_closed")
            quarantine = self._quarantine.get(plugin_id)
            if quarantine is not None and time.monotonic() < quarantine[1]:
                raise PluginRuntimeError("plugin_quarantined", quarantine[0])
            worker = self._workers.get(plugin_id)
            if (
                worker is not None
                and not worker.closed
                and worker.ready.is_set()
                and worker.ready_ok
            ):
                worker.last_activity = time.monotonic()
                return worker
            lock = self._worker_locks.setdefault(plugin_id, threading.Lock())
        with lock:
            with self._lock:
                worker = self._workers.get(plugin_id)
                if (
                    worker is not None
                    and not worker.closed
                    and worker.ready.is_set()
                    and worker.ready_ok
                ):
                    worker.last_activity = time.monotonic()
                    return worker
                spec = self._resolve_spec(plugin_id)
                if worker is not None and not worker.closed:
                    self._stop_worker(worker, "restart", intentional=True)
            return self._start_worker(plugin_id, spec)

    # 解析插件版本，统一转换为 runtime 错误
    def _resolve_spec(self, plugin_id):
        try:
            return self._resolver(plugin_id)
        except Exception as error:
            reason = getattr(error, "reason", "plugin_missing")
            raise PluginRuntimeError(reason, str(error)) from error

    # 启动 worker 并等待 ready 握手
    def _start_worker(self, plugin_id, spec):
        self._check_capacity()
        self._check_restart_budget(plugin_id)
        token = uuid.uuid4().hex
        worker = WorkerHandle(plugin_id, spec, token)
        self._workers[plugin_id] = worker
        worker.started_at = time.monotonic()

        def handle_request(method, params):
            return self._handle_request(worker, method, params)

        def handle_notification(method, params):
            self._handle_notification(worker, method, params)

        def handle_close(reason):
            self._handle_worker_closed(worker, reason)

        try:
            worker.process = self._spawn(
                self._worker_argv(plugin_id, token), self._worker_env()
            )
            worker.channel = RpcChannel(
                worker.process.stdout,
                worker.process.stdin,
                on_request=handle_request,
                on_notification=handle_notification,
                on_close=handle_close,
                name="plugin-" + plugin_id,
            )
            worker.channel.start()
        except Exception as error:
            self._workers.pop(plugin_id, None)
            raise PluginRuntimeError("spawn_failed", str(error)) from error
        threading.Thread(
            target=self._pump_stderr,
            args=(worker,),
            name="plugin-stderr-" + plugin_id,
            daemon=True,
        ).start()
        if not worker.ready.wait(HANDSHAKE_TIMEOUT):
            self._stop_worker(worker, "handshake_timeout", intentional=True)
            raise PluginRuntimeError("handshake_timeout", plugin_id)
        if not worker.ready_ok:
            self._stop_worker(worker, "plugin_load_failed", intentional=True)
            raise PluginRuntimeError("plugin_load_failed", worker.ready_error)
        worker.last_activity = time.monotonic()
        return worker

    # 启动 worker 进程的命令行（冻结版自我 re-exec）
    def _worker_argv(self, plugin_id, token):
        base = [
            "--plugin-worker",
            "--plugin-id",
            plugin_id,
            "--token",
            token,
        ]
        if getattr(sys, "frozen", False):
            return [sys.executable, *base]
        return [sys.executable, "-m", "ohmymeme.plugin_worker", *base]

    # 为源码运行补齐 PYTHONPATH
    def _worker_env(self):
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        if not getattr(sys, "frozen", False):
            import ohmymeme

            src_root = str(Path(ohmymeme.__file__).resolve().parents[1])
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = src_root + (os.pathsep + existing if existing else "")
        return env

    # 处理宿主侧容量上限
    def _check_capacity(self):
        if len(self._workers) >= MAX_WORKERS:
            raise PluginRuntimeError("worker_limit", "too many workers")

    # 崩溃退避与熔断
    def _check_restart_budget(self, plugin_id):
        now = time.monotonic()
        crashes = [
            item
            for item in self._crashes.get(plugin_id, ())
            if now - item < RESTART_WINDOW
        ]
        if len(crashes) >= RESTART_LIMIT:
            self._quarantine[plugin_id] = ("crash_loop", now + RESTART_WINDOW)
            raise PluginRuntimeError("plugin_quarantined", "crash_loop")
        self._crashes[plugin_id] = crashes
        if crashes:
            time.sleep(min(2.0 ** (len(crashes) - 1), RESTART_BACKOFF))

    # 把 stderr 日志挂到宿主 logger
    def _pump_stderr(self, worker):
        stream = worker.process.stderr
        try:
            for raw in iter(stream.readline, b""):
                line = raw.decode("utf-8", "replace").rstrip()
                if line:
                    logger.info("[plugin %s] %s", worker.plugin_id, line)
        except (OSError, ValueError):
            pass
        finally:
            try:
                stream.close()
            except OSError:
                pass

    # 处理 worker 发来的握手与操作请求
    def _handle_request(self, worker, method, params):
        if method == "hello":
            return self._handle_hello(worker, params)
        if method == "ready":
            worker.ready_ok = bool(params.get("ok"))
            worker.ready_error = str(params.get("error") or "")
            worker.ready.set()
            return {"ok": True}
        if method in (
            "sink.import_batch",
            "sink.import_path",
            "config.set",
            "helper.wechat",
        ):
            return self._handle_operation_request(worker, method, params)
        if method == "nickname.lookup":
            return self._handle_lookup(worker, params)
        raise RpcError(protocol.RPC_METHOD_NOT_FOUND, "unknown method")

    # 查询期间开放的宿主回调
    def _handle_lookup(self, worker, params):
        query_id = params.get("query_id")
        with self._lock:
            query = self._queries.get(query_id)
        if query is None or query.get("worker") is not worker:
            raise RpcError(protocol.ERROR_OPERATION_UNKNOWN, "unknown query")
        callback = query.get("nickname_lookup")
        if callback is None:
            raise RpcError(protocol.ERROR_UNSUPPORTED, "lookup unavailable")
        return callback(str(params.get("qq") or ""))

    # 校验握手身份并下发布局信息
    def _handle_hello(self, worker, params):
        if (
            params.get("protocol_version") != protocol.PROTOCOL_VERSION
            or params.get("plugin_id") != worker.plugin_id
            or params.get("token") != worker.token
        ):
            return {"accepted": False, "reason": protocol.ERROR_REJECT}
        spec = worker.spec
        return {
            "accepted": True,
            "protocol_version": protocol.PROTOCOL_VERSION,
            "plugin": {
                "id": spec["id"],
                "version": spec.get("version", ""),
                "entry": spec.get("entry", ""),
                "package_dir": spec.get("package_dir", ""),
                "package_root": spec.get("package_root", ""),
                "kind": spec.get("kind", ""),
                "capabilities": list(spec.get("capabilities") or ()),
            },
        }

    # 把操作请求路由到对应记录
    def _handle_operation_request(self, worker, method, params):
        op_id = params.get("op_id")
        with self._lock:
            record = self._operations.get(op_id)
        if record is None or record.worker is not worker:
            raise RpcError(protocol.ERROR_OPERATION_UNKNOWN, "unknown operation")
        worker.last_activity = time.monotonic()
        if method == "sink.import_batch":
            if record.sink_batch is None:
                raise RpcError(protocol.ERROR_UNSUPPORTED, "sink unavailable")
            return record.sink_batch(list(params.get("requests") or ()))
        if method == "sink.import_path":
            if record.sink_path is None:
                raise RpcError(protocol.ERROR_UNSUPPORTED, "sink unavailable")
            return record.sink_path(dict(params.get("request") or {}))
        if method == "helper.wechat":
            if record.helper_wechat is None:
                raise RpcError(protocol.ERROR_UNSUPPORTED, "helper unavailable")
            return record.helper_wechat()
        if record.config_set is None:
            raise RpcError(protocol.ERROR_UNSUPPORTED, "config unavailable")
        record.config_set(str(params.get("key") or ""), params.get("value"))
        return {"ok": True}

    # 处理 worker 通知：进度、日志、操作结束、子进程登记
    def _handle_notification(self, worker, method, params):
        worker.last_activity = time.monotonic()
        op_id = params.get("op_id")
        with self._lock:
            record = self._operations.get(op_id)
        if record is None:
            return
        if method == "progress":
            if record.on_progress is not None:
                record.on_progress(params.get("value"))
            return
        if method == "log":
            if record.on_log is not None:
                record.on_log(params.get("value"))
            return
        if method == "process.registered":
            logger.debug(
                "plugin %s registered process %s", worker.plugin_id, params.get("pid")
            )
            return
        if method == "operation.finished":
            outcome = {
                "ok": bool(params.get("ok")),
                "result": params.get("result"),
                "error": str(params.get("error") or ""),
            }
            record.outcome = outcome
            record.done.set()
            self._forget_operation(record)

    # worker 退出：标记关闭并结束在途操作
    def _handle_worker_closed(self, worker, reason):
        with self._lock:
            worker.closed = True
            if self._workers.get(worker.plugin_id) is worker:
                self._workers.pop(worker.plugin_id, None)
            if not worker.stopping:
                crashes = self._crashes.setdefault(worker.plugin_id, [])
                crashes.append(time.monotonic())
            records = list(worker.operations.values())
        for record in records:
            record.outcome = {
                "ok": False,
                "result": None,
                "error": "worker_closed: %s" % reason,
            }
            record.done.set()
            self._forget_operation(record)
        if not worker.stopping and reason != "eof":
            logger.warning("plugin worker closed: %s (%s)", worker.plugin_id, reason)

    # 从操作表移除记录
    def _forget_operation(self, record):
        with self._lock:
            self._operations.pop(record.op_id, None)
        record.worker.operations.pop(record.op_id, None)

    # 启动一次插件操作
    def start_operation(
        self,
        plugin_id,
        kind,
        request,
        workspace,
        config=None,
        secrets=None,
        listing=False,
        progress=None,
        log=None,
        sink_batch=None,
        sink_path=None,
        config_set=None,
        helper_wechat=None,
    ):
        worker = self.ensure(plugin_id)
        op_id = uuid.uuid4().hex
        record = RuntimeOperation(
            self,
            worker,
            op_id,
            kind,
            {
                "progress": progress,
                "log": log,
                "sink_batch": sink_batch,
                "sink_path": sink_path,
                "config_set": config_set,
                "helper_wechat": helper_wechat,
            },
        )
        with self._lock:
            self._operations[op_id] = record
        worker.operations[op_id] = record
        try:
            result = worker.channel.call(
                "operation.start",
                {
                    "op_id": op_id,
                    "kind": kind,
                    "request": dict(request or {}),
                    "config": dict(config or {}),
                    "secrets": dict(secrets or {}),
                    "workspace": str(workspace),
                    "listing": bool(listing),
                },
                timeout=OPERATION_START_TIMEOUT,
            )
        except Exception:
            self._forget_operation(record)
            raise
        if not isinstance(result, dict) or not result.get("accepted"):
            self._forget_operation(record)
            reason = (result or {}).get("reason", "operation_rejected")
            raise PluginRuntimeError(reason)
        record.initial_progress = result.get("progress")
        return record

    # 执行插件声明过的 UI 动作（worker 按 ui.json allowlist 校验）
    def call_ui_action(self, plugin_id, name, payload=None):
        worker = self.ensure(plugin_id)
        return worker.channel.call(
            "ui.action",
            {"name": str(name), "payload": dict(payload or {})},
            timeout=REQUEST_TIMEOUT,
        )

    # 打开同步 backend 会话，供宿主 backends 适配层逐方法调用
    def open_backend(self, provider_id, config, secrets, enabled=None):
        if enabled is not None and provider_id not in enabled:
            raise PluginRuntimeError("provider_disabled", provider_id)
        worker = self.ensure(provider_id)
        session_id = uuid.uuid4().hex
        payload = config._asdict() if hasattr(config, "_asdict") else dict(config)
        worker.channel.call(
            "sync.open",
            {
                "session_id": session_id,
                "provider_id": provider_id,
                "config": payload,
                "secrets": dict(secrets or {}),
            },
            timeout=REQUEST_TIMEOUT,
        )
        return RuntimeSyncSession(worker, session_id)

    # 打开 LAN transport 会话；socket 与发现都留在 worker
    def open_lan(self, config):
        worker = self.ensure("transport.lan")
        session_id = uuid.uuid4().hex
        payload = config._asdict() if hasattr(config, "_asdict") else dict(config)
        result = worker.channel.call(
            "lan.open",
            {"session_id": session_id, "config": payload},
            timeout=REQUEST_TIMEOUT,
        )
        return RuntimeLanTransport(
            worker,
            session_id,
            result.get("port", 0),
            bool(result.get("pktinfo")),
        )

    # 查询本机 LAN IP
    def get_lan_ip(self):
        worker = self.ensure("transport.lan")
        result = worker.channel.call("lan.get_ip", {}, timeout=REQUEST_TIMEOUT)
        return str(result.get("ip") or "")

    # 请求取消操作，worker 失联时静默放弃
    def cancel_operation(self, record):
        channel = record.worker.channel
        if channel is None or channel.is_closed():
            return
        try:
            channel.call(
                "operation.cancel",
                {"op_id": record.op_id},
                timeout=10.0,
            )
        except (ChannelClosed, RpcError):
            pass

    # 同步查询插件方法（inspect 等固定查询）
    def query(
        self,
        plugin_id,
        method,
        params=None,
        timeout=REQUEST_TIMEOUT,
        nickname_lookup=None,
    ):
        worker = self.ensure(plugin_id)
        query_id = uuid.uuid4().hex
        with self._lock:
            self._queries[query_id] = {
                "worker": worker,
                "nickname_lookup": nickname_lookup,
            }
        try:
            return worker.channel.call(
                "plugin.query",
                {
                    "method": method,
                    "params": dict(params or {}),
                    "query_id": query_id,
                },
                timeout=timeout,
            )
        except ChannelClosed as error:
            raise PluginRuntimeError("worker_closed", str(error)) from error
        finally:
            with self._lock:
                self._queries.pop(query_id, None)

    # 心跳：探活、失败熔断、空闲回收
    def _heartbeat_loop(self):
        while True:
            time.sleep(PING_INTERVAL)
            with self._lock:
                if self._closed:
                    return
                workers = [
                    worker
                    for worker in self._workers.values()
                    if not worker.closed and worker.ready.is_set()
                ]
            now = time.monotonic()
            for worker in workers:
                if not worker.operations and now - worker.last_activity > IDLE_TTL:
                    self._stop_worker(worker, "idle", intentional=True)
                    continue
                if not worker.pinging:
                    worker.pinging = True
                    threading.Thread(
                        target=self._ping_worker,
                        args=(worker,),
                        name="plugin-ping-" + worker.plugin_id,
                        daemon=True,
                    ).start()

    # 单个 worker 的探活，失败累计后强制回收
    def _ping_worker(self, worker):
        try:
            worker.channel.call("ping", {}, timeout=PING_TIMEOUT)
            worker.ping_failures = 0
            worker.last_activity = time.monotonic()
        except Exception:
            worker.ping_failures += 1
            if worker.ping_failures >= PING_FAILURE_LIMIT:
                logger.warning("plugin worker unresponsive: %s", worker.plugin_id)
                self._stop_worker(worker, "unresponsive", intentional=False)
        finally:
            worker.pinging = False

    # 停止 worker：先请求关闭再整树回收
    def _stop_worker(self, worker, reason, intentional):
        worker.stopping = intentional
        channel = worker.channel
        if channel is not None and not channel.is_closed():
            try:
                channel.call("shutdown", {}, timeout=5.0)
            except Exception:
                pass
        if worker.process is not None:
            process_tree.kill_tree(worker.process, timeout=5.0)
        if channel is not None:
            channel.close(reason)
        with self._lock:
            if self._workers.get(worker.plugin_id) is worker:
                self._workers.pop(worker.plugin_id, None)

    # 停止单个插件 worker（重载/安装/卸载前置）
    def stop_plugin(self, plugin_id, reason="reload"):
        with self._lock:
            worker = self._workers.get(plugin_id)
        if worker is not None:
            self._stop_worker(worker, reason, intentional=True)
        return True

    # 关闭全部 worker 与后台线程
    def shutdown(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            workers = list(self._workers.values())
        for worker in workers:
            self._stop_worker(worker, "shutdown", intentional=True)
        with self._lock:
            self._workers.clear()
            self._operations.clear()
