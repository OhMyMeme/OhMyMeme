## Summary

- 新增 src/tg_stickers.py：完整的 Telegram Desktop 缓存解密与转换管线（TDF$/TDEF 解密、webm→animated webp 无损转换保留 alpha、静态版去重、状态轮询）
- 设置页「从 Telegram 导入」向导（tdata 目录选择/本地密码/WebM 转换开关/进度覆盖层）
- ffmpeg 转 webp 使用 libvpx-vp9 解码器修复透明动画丢失（原生 vp9 解码器会丢弃 alpha 平面）
- 新增 `hover_to_play` 配置项：启用后网格显示缩略图，鼠标悬停才播放动图，解决多 3MB 动画 webp 同时渲染卡顿

## Changes

### 1. Telegram 缓存导入 (`feat`)

- `src/tg_stickers.py`（~620 行）
  - TDF$/TDEF 格式解密（AES-CTR，PBKDF2 密钥派生）
  - webm → animated webp 无损转换（`-c:v libvpx-vp9` 保留 alpha 平面）
  - 静态 webp vs 动画 webp 去重（归一化灰度差分，阈值 0.02）
  - 状态轮询：idle→scanning→loading_key→decrypting→converting→importing→done/error/cancelled
- 设置页「从 Telegram 导入」向导
  - tdata 目录手动选择（校验 key_datas 后持久化）
  - 本地密码输入（可选）
  - WebM 转 WebP 开关（默认开，需 ffmpeg）
  - 进度覆盖层（300ms 轮询 + 错误码映射重试按钮）
- `config.py` 新增 `tg_tdata_path`

### 2. 动图悬停播放 (`perf`)

- 问题：网格中 20+ 个 3MB 512×512 30 帧动画 webp 同时播放，WebView2 复合层饱和掉帧
- 方案：`hover_to_play` 配置项，启用后网格默认缩略图，悬停 150ms 切原图播放，离开立即切回
- `index.js` 抽取 `setupHoverPlay()` 助手消除重复逻辑
- 效果：同时播放动画数从 N 降至 1-2，GPU 显存从 600MB+ 降至 ~60MB

### 3. Code Review 修复 (`fix`)

- `SettingsApi.get_settings()` 补充返回 `hover_to_play`，修复设置页复选框状态丢失
- hover 门控解耦：`is_animated && hover_to_play`（独立于 auto_play_gif 生效）
- tg_stickers 解密循环单独捕获 RuntimeError，依赖缺失 re-raise 而非静默吞掉
- `start_tg_import` 添加 `_TG_LOCK` 并发守卫，running 拒绝重复启动
- settings.js TG import API 包裹 try/catch + finally，轮询 20 次 null 上限
- 导入完成后清空密码字段
- 所有 DOM 元素访问添加 null 检查

## Test plan

- [ ] 自动检测 tdata 路径并成功导入（无本地密码）
- [ ] 手动指定 tdata 路径并持久化，重启后保留
- [ ] 带本地密码的 tdata 解密
- [ ] WebM 转换开关关闭时跳过 webm 文件
- [ ] 无 ffmpeg 时友好报错
- [ ] 重复点击「提取」按钮不会启动多个 worker
- [ ] `hover_to_play=true` 时网格显示缩略图，悬停播放动画
- [ ] `hover_to_play=true` + `auto_play_gif=false` 时悬停仍可播放
- [ ] 设置页关闭再打开，复选框状态保留
