# PR 描述

**标题**：`fix: WebDAV 同步重复 MKCOL 触发远端锁 + 全局快捷键运行期失效自愈`

**类型**：缺陷修复（WebDAV 同步稳定性、Windows 全局快捷键运行期失效）

## 背景

用户实测反馈两个问题：
1. **WebDAV 同步频繁执行创建目录导致触发远端锁**：多线程上传时对同一 `memes/` 目录反复发 `MKCOL`，服务器端判定为目录级锁竞争并加锁，同步被卡死。
2. **更新后的版本快捷键呼出出现失灵**：Windows 下用着用着热键突然失效，重启软件才恢复（高频偶发，一小时可达两次）。

## 变更内容

### 1. WebDAV 目录创建去重（`src/sync.py`）

- `_push_worker` 同一批次所有文件都上传到 `memes/` 目录，原来对**每个文件**都调用 `ensure_remote_dir`；改为循环前用 `remote_dir_ready` 标志**只确保一次**。
- `_WebDAVBackend.ensure_remote_dir` 增加进程级目录缓存 `_dav_dirs`（`_dav_dirs_lock` 保护）：已确认存在的目录 URL 后续直接跳过，不再重复发 `MKCOL`。多 worker 并发对同一目录也只会在首次确认时发一次 MKCOL。
- 效果：上传 N 个文件时 MKCOL 请求数从 `O(N × 路径深度)` 降为 `O(路径深度)`，避免触发远端锁。

### 2. 全局快捷键运行期失效自愈（`src/hotkey.py`）

根因：`keyboard` 0.13.5 的 `GenericListener` 处理线程（`processing_thread`）一旦因**未捕获异常**崩溃即永久退出——进程存活、界面正常，但热键全部失效，需重启软件才能恢复（与用户症状完全吻合）。

两道防线：
- **回调吞异常**：`_try_keyboard` 用 `make_safe` 把热键回调包成 `_safe_callback`，回调内异常被 try/except 吞掉并记录，防止其杀死 `processing_thread`。
- **守护线程自动重注册**：注册成功后启动 daemon 守护线程（`_start_keyboard_watchdog`，`KEYBOARD_WATCH_INTERVAL`=5s），周期性检查 `keyboard._listener` 的 `listening_thread`/`processing_thread` 是否存活；任一死亡即 `_reregister_keyboard`（`remove_hotkey` → 置 `listener.listening=False` → `start_if_necessary()` → 重新 `add_hotkey`）自动重挂，无需用户重启软件。`unregister` 先停守护再注销，避免注销后被自动重挂。

### 3. 热键事件日志（`src/hotkey.py`）

- 新增独立文件日志：`_get_file_logger` 惰性创建 logger，把**注册成功 / 回调异常 / 线程死亡 / 自动自愈重挂**等事件追加到 `data_dir/hotkey.log`（带时间戳，同时写控制台）。初始化失败降级为常规 logger，不影响运行。
- 便于用户在 Windows 上复盘：热键若失效，日志能区分「从未失效」「已自愈恢复」「自愈失败需进一步查」。

### 4. 测试与文档

- `tests/test_webdav_backend.py`：新增 `test_second_call_skips_mkcol`（第二次 `ensure_remote_dir` 不再发 MKCOL）；`setUp` 清空进程级缓存保证测试隔离。
- `tests/test_core.py`：新增 `TestHotkeyWatchdog`（mock `keyboard` 模块验证自动重注册调用序列、`unregister` 停守护并清回调）。
- `AGENTS.md` / `README.md`：同步补充自愈机制、日志文件与 WebDAV 目录缓存说明。

## 验证

- `black --check src/`、`ruff check src/` 全部通过
- `tests.test_core` + `tests.test_sync` + `tests.test_webdav_backend` 共 **98 例全部通过**
- 真实触发验证：`hotkey.log` 正确生成于 `data_dir`，内容带时间戳与级别
- Windows 实机长时间使用（一整天）未再出现热键失效反馈

## 已知限制

- Windows 实机上尝试过自动化注入验证（`SendInput`），但该机器环境（360/AMD overlay 等 LL 钩子）会吞掉注入键事件，注入路径不可用；改为真实使用 + `hotkey.log` 日志复盘确认。
- 守护线程访问 `keyboard._listener` 等内部属性，若未来升级 `keyboard` 改动内部结构可能失效，届时需适配。

## 代码审查修复

针对 review 意见加固，集中为并发正确性：

- **sync（MKCOL 原子化）**：`ensure_remote_dir` 把「缓存检查 + MKCOL + 缓存写入」整体放入 `_dav_dirs_lock` 原子执行；成功/405/复核命中均写缓存。修复了「两个并发 worker 都发现目录未缓存 → 并发发 MKCOL」的竞态，目录级锁竞争彻底消除。
- **hotkey（重注册失败不再误报成功）**：`_reregister_keyboard` 改为返回 bool；`add_hotkey` 失败时置 `_reregister_pending=True` 并返回 False（不再无条件记成功），守护线程下一周期继续重试，直到注册成功。
- **hotkey（注销与重注册并发）**：`unregister` 与 `_reregister_keyboard` 持同一 `_reregister_lock` 串行化，并在重注册入口复查「回调已清空 / 停止事件已置位」；注销完成后再也不重新挂热键，也不会把已清空的回调传给 `add_hotkey`。
- **回归测试**：新增 `test_reregister_add_failure_sets_pending_and_not_success`、`test_reregister_after_unregister_does_not_add`、`test_success_also_caches_and_single_mkcol`；既有 fast 重注册用例补充守护启动态。共 101 例全部通过。

