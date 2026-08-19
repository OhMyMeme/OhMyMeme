# OhMyMeme Android

> **重要说明：安卓版悬浮窗功能仍在开发中，当前属于不完全版。** 如果悬浮窗在你的设备上可以正常使用，可以按需使用；如果无法使用，请忽略悬浮窗，不影响其他功能。除悬浮窗外的导入、搜索、文件夹、AI、分享包、同步等功能可正常使用。遇到 Bug 请联系：<https://luckywszl.top>。
>
> **项目说明：本人并不擅长 Android 等移动端软件开发。** 如果有熟悉 Android 开发的开发者愿意接替或继续维护这个项目，欢迎基于本项目继续开发、修复和完善。

轻量化表情包管理系统的安卓端 — 与桌面端（[OhMyMeme](https://github.com/OhMyMeme/OhMyMeme)）存储结构一致，便于多端同步。

![picture](https://raw.githubusercontent.com/OhMyMeme/OhMyMeme-Android/refs/heads/dev/resource/picture.gif)

## 功能

- **暗色 UI 复刻** — 主界面 / 设置页严格对照桌面端（暗色主题、标题栏、搜索框、分组胶囊、3 列表情网格）
- **表情导入** — 点击「导入」弹出菜单：从文件导入（系统文件选择器批量导入 png/jpg/jpeg/gif/webp/bmp）/ 从手机相册导入（Photo Picker，免权限，不支持时回退系统相册选择器）/ 从文件夹导入（SAF 递归扫描，根目录建同名分组、一级子目录建小分组；更深目录归入最近一级分组，且新增表情补充分组同名标签）/ 从手机QQ缓存导入（占位，后续用 Shizuku 实现）；SHA-256 哈希去重，自动重命名为 `{hash前16位}{真实扩展名}`
- **缓存扫描** — 启动/手动刷新时扫描缓存目录，已有文件自动注册到数据库（文件名 + 哈希双重去重）
- **缩略图** — 懒生成缩略图到 `thumbnails/{meme_id}_{size}.png`，网格加载
- **本地数据库** — SQLite (WAL)，7 表 schema 与桌面端 `src/database.py` 完全一致（memes/tags/meme_tags/collections/meme_collections/favorites/recent_uses）
- **搜索与标签** — 关键词实时筛选（按文件名/原始名/AI 描述/图片文字），可从单张表情菜单编辑标签；标签栏支持多选交集筛选，分组/收藏夹/最近使用/未分类胶囊可与标签条件叠加。标签失去全部引用后自动清理，与桌面端 `search_memes` 一致
- **「未分类」分组** — 顶栏胶囊显示未加入任何分组的表情（虚拟分组 `id == -4`，对齐桌面端 `webui.py`），仅在存在未分类表情时显示；可在设置页「显示『未分类』分组」开关控制，默认开
- **小分组** — 顶栏分组胶囊长按新建小分组（仅 1 层，对齐桌面端 `create_subcollection`），子分组胶囊在父分组激活时平铺展开（对齐桌面端 webui 顶栏 `renderCollections`）；表情长按「加入小分组」可选目标子分组或新建，对齐桌面端网格右键
- **文件夹管理** — 顶栏统一按文件夹展示，空文件夹也会保留；「更多」可新建文件夹，长按文件夹可新建一层小分组、重命名或删除（仅移除归属，不删除表情和同名标签）。表情菜单的“放入文件夹”可选择顶层或小分组，并以“父文件夹 / 小分组”标识路径；复制保留原有全部归属，移动清除其他归属；两者都会自动补充目标文件夹同名标签，对齐桌面端文件夹语义。
- **分页与网格** — 大图库按每页 200 张加载，底部可继续加载更多；设置页可选 2–6 列网格。拖拽排序仅在首个未筛选页面的全局视图或真实分组视图启用，避免分页或标签筛选时写入不完整排序。
- **设置** — 动图开关、复制处理模式、云端同步（FTP/S3/R2/WebDAV）凭据、版本信息、危险操作；保存/恢复默认已接真实配置（密钥字段用 Android Keystore 加密存储）
- **配置加密** — `config.json` 中的密钥字段（包括同步密码及 AI API Key）经 Android Keystore AES-GCM 加密后落盘
- **AI 工作流** — 设置页分别配置 AI 整理与 AI 图片服务（各自 Base URL、API Key、模型，兼容 OpenAI 格式接口）；可配置每次 AI 整理数量（1–500，默认 50）。主界面「更多」菜单提供 AI 整理、AI 找图、AI 生图，单张表情「⋯」菜单提供 AI 图片编辑。AI 整理会显示逐项进度，随后进入可滚动审核页；每条建议均可编辑标签、文件夹、图片描述和 OCR 文本，只有确认应用后才写入。生图、找图和编辑结果均走统一导入、校验与 SHA-256 去重，图片编辑永远作为副本导入，不覆盖原图
- **AI 元数据同步** — `meme-index.json` v3 包含 `ai_description`、`ai_ocr_text`；云同步和局域网拉取都会同步这两个字段，保证桌面端与 Android 端的搜索语义一致
- **悬浮搜索窗（开发中，不完全版）** — 可从主界面「更多」或设置页尝试开启系统悬浮按钮。该功能仍在开发中，部分设备或系统可能无法正常使用；如果无法使用，请直接忽略，不影响其他功能。所有路线均不会自动点击发送按钮、发送消息、读取聊天记录或监听剪贴板。问题反馈：<https://luckywszl.top>。
- **分享包互通** — 支持导入和导出桌面端兼容的 `.ohmymeme-pack` v1 ZIP 包（`metadata.json` + `images/`）。导入会校验 ZIP 路径、数量、总大小、图片扩展名和图片内容，按 SHA-256 跳过重复图片；新图片恢复标签、收藏、分组和排序。可在「导入」菜单导入，在单张表情菜单导出，或从「更多」导出全部。
- **版本更新检查** — 设置页「检查更新」查询 GitHub Releases（`OhMyMeme/OhMyMeme-Android`），发现新版本弹窗引导下载 APK；下载地址按桌面端镜像列表依次探测可用镜像（github.dpik.top / gh.dpik.top / gh-proxy.org / proxy.starsfire.top），失败回退 GitHub 直连
- **云端同步** — 设置页选择 FTP / S3 / R2 / WebDAV 任一后端，配置凭据后可「测试连接 / 检查同步状态 / 上传到远端 / 从远端下载 / 清理云端孤儿」；远端目录结构与桌面端一致（`memes/` 文件 + `meme-index.json` 清单 v3），SHA-256 比对跳过已同步文件，上传可删除远端多余文件、下载可移除本地多余文件并重建远端分组；同步多线程并发（`sync_threads`，默认 3），主界面一键同步带进度条 / 百分比 / 速度 / 后台运行，完成弹窗提示，均可由设置项控制；可在设置中开启启动时自动获取远端索引 / 自动同步
- **动图播放** — GIF/WebP 动图在网格中直接播放（受设置页「动图自动播放」开关控制），右上角显示 GIF/WebP/隐写导入角标
- **长按右键菜单** — 长按表情弹出菜单：重命名 / 收藏 / 添加分组 / 加入小分组 / 从分组移除 / 从最近使用中删除 / 删除，对齐桌面端 webui；分组移除后为空则自动删除该分组（小分组移回上层）
- **点击分享** — 点击表情卡片经系统分享面板（FileProvider + `ACTION_SEND`）把图片分享到微信/QQ 等，同时自动记入最近使用；分享前按设置页「复制处理」模式处理超限静态图（1=缩放为 WebP、2=转为 GIF、3=转为隐写 GIF，对齐桌面端 `convert_image_mode_1/2/3`），动图/未超限直接发原图
- **接收分享导入** — 从任意应用（微信/QQ/浏览器等）分享图片到 OhMyMeme 即可直接导入（`ACTION_SEND`/`ACTION_SEND_MULTIPLE`）
- **最近使用** — 点击表情卡片自动记入最近使用，最近使用分组实时刷新
- **日志导出** — 设置页导出本次运行的 Debug 日志（logcat 按进程 PID 过滤）到用户选择的位置
- **快捷同步** — 主界面标题栏「更多」菜单提供上传到远端 / 从远端下载，一键同步并保留既有进度与完成提示
- **局域网互联** — 设置页连接同一局域网内的电脑端 OhMyMeme（UDP 发现 + AES-GCM 加密会话）：扫描发现电脑或 **IP:端口 直连**（跳过扫描直接连接）、输入密钥配对、连接时发送设备信息待电脑端确认、从电脑拉取表情（逐文件校验文件名/大小/哈希/可解码）、把手机表情上传到电脑、配置双向同步（拉取/推送弹窗确认）、密钥同步（电脑端开启「允许密钥传输」后动态显示「拉取密钥/推送密钥」按钮，弹窗警告后同步），对齐桌面端 `lan.py` 协议
- **存储位置** — 设置页可修改数据位置（SAF 目录选择器），cache/thumbnails 转移至所选目录（经 content URI 读写，memes.db 保留在真实路径）；可选择转移现有文件；配置文件 config.json 保持不变
- **控制中心快捷按钮** — 系统快捷设置磁贴（TileService），点击一键打开 OhMyMeme；设置页「快捷开关」区块提供添加指引
- **长按拖拽发送** — 长按网格卡片直接把表情拖入微信/QQ 等聊天窗口（相册式跨应用 Drag & Drop，ClipData + FileProvider URI + `DRAG_FLAG_GLOBAL_URI_READ`，SAF 模式自动物化）；卡片右上角「⋯」按钮打开右键菜单（重命名/收藏/分组/删除），拖拽未被接收时自动弹出兜底

## 快速开始

### 环境要求

- Android Studio（AGP 9.0.0, Gradle 9.1）
- JDK 17+
- Android SDK 36（compileSdk）、minSdk 28

### 构建

```bash
# 构建 Release APK（已签名，产物 OhMyMeme-Android-{版本}.apk）
./gradlew :app:assembleRelease

# 仅编译 Kotlin（快速验证）
./gradlew :app:compileDebugKotlin
```

产物输出到 `app/build/outputs/apk/release/OhMyMeme-Android-{versionName}.apk`。

> **签名说明**：Release 与 Debug 共用一把共享密钥（`keystore/ohmymeme-release.jks`，来自私有仓库
> `OhMyMeme/OhMyMeme-Android-keystore`），保证本地/CI 所有 APK 签名一致、可互相覆盖安装。
> 新成员先运行 `scripts/setup-keystore.ps1` 获取密钥（详见 `keystore/README.md`）；
> 没有密钥时打包会报错（刻意为之，保证签名一致）。Debug 构建使用同一密钥，安装调试包与正式包互不冲突。

### CI

GitHub Actions 两个工作流（参考桌面端 `.github/workflows`）：

- `Check` — 每次 push / PR 运行：`compileDebugKotlin` + `lintDebug` + `testDebugUnitTest`（JDK 17）
- `Build` — Check 通过（main 分支）或手动触发时运行 `assembleRelease`，产出已签名 Release APK
  `OhMyMeme-Android-{版本}.apk` 并上传为 artifact；签名密钥由 GitHub Secrets 解码（见下）

### GitHub Secrets（签名密钥）

仓库 Secrets 需配置 4 项（`Settings → Secrets and variables → Actions`）：

| Secret | 值 |
|--------|-----|
| `SIGNING_KEYSTORE_BASE64` | `keystore/ohmymeme-release.jks` 的 base64（`certutil -encode` 或 `base64` 命令生成） |
| `SIGNING_STORE_PASSWORD` | keystore 密码 |
| `SIGNING_KEY_ALIAS` | 密钥别名（默认 `ohmymeme`） |
| `SIGNING_KEY_PASSWORD` | 密钥密码 |

本地构建则读项目根 `keystore.properties`（gitignored，由 `scripts/setup-keystore.ps1` 从私有密钥仓库拷贝生成）。

### 安装

将 Release APK（`OhMyMeme-Android-{版本}.apk`）直接安装到 Android 手机（需开启「允许安装未知来源应用」），
或通过 Android Studio 连接设备直接运行（Debug 构建使用同一签名，可覆盖安装 Release 包）。

## 使用

### 基本操作

1. **启动** — 打开应用，首次运行会询问存储位置；标题栏为蓝色 "Meme" 字样，下方为搜索框
2. **导入** — 点击标题栏「导入」按钮，从系统文件选择器选图片（支持多选），自动去重并加入网格
3. **更多** — 点击标题栏「更多」菜单，可上传到远端、从远端下载，或选择「刷新」重新扫描缓存目录并注册已有文件
4. **搜索** — 搜索栏输入关键词实时筛选，点击分组胶囊过滤
5. **设置** — 点击⚙按钮进入设置页，修改后点「保存」持久化，「恢复默认」还原出厂配置

### AI 功能

1. 在「设置 → AI 功能」分别填写 AI 整理服务和 AI 图片服务的 Base URL、API Key、模型；API Key 由 Android Keystore 加密保存。
2. 选择「更多 → AI 整理图库」时，应用只会把待整理的图片发送给你配置的 AI 服务。结果先显示为审核建议，确认后才会写入标签、分组、AI 描述和 OCR 文本。
3. 「AI 找图」从 Bing 图片搜索结果中下载用户主动选择的关键词结果；「AI 生图」和「AI 编辑副本」调用你配置的图片服务。生图、找图和编辑副本均作为新表情导入，保留原图。
4. AI 描述和 OCR 文本会进入本地搜索，并随 `meme-index.json` 在桌面端、Android 端、云同步与局域网同步之间传递。

> AI 请求会消耗你配置服务的额度，并可能将图片或提示词发送至该服务。Android 版不会读取、监听或控制 QQ、微信等聊天应用。

### 路径说明

与桌面端存储结构保持一致，便于互相同步：

| 用途 | 路径 |
|------|------|
| 数据根目录 | `Android/data/com.ohmymeme.app/` |
| 配置文件 | `Android/data/com.ohmymeme.app/config.json` |
| 数据库 | `Android/data/com.ohmymeme.app/files/memes.db`（始终在真实路径） |
| 缓存原图 | 默认 `files/cache/`；用户经 SAF 指定目录后位于所选目录的 `cache/` |
| 缩略图 | 默认 `files/thumbnails/`；用户经 SAF 指定目录后位于所选目录的 `thumbnails/` |

> 首次运行会弹出对话框选择存储位置：默认使用应用专属目录，或通过系统目录选择器（SAF）指定其他位置。SAF 模式下 cache/thumbnails 经 content URI 读写（作用域存储下共享目录无法以原始文件路径写入），memes.db 始终留在应用可真实写入的 `files/` 目录；切换存储位置时可选择把现有 cache/thumbnails 转移到新目录。存储结构对应桌面端：`config.json` ↔ `%APPDATA%/OhMyMeme/config.json`，`files/` ↔ `%LOCALAPPDATA%/OhMyMeme`（含 memes.db / cache / thumbnails），后续可扩展远程同步。

## 架构

```
┌─────────────┐      ┌───────────────┐
│ MainActivity │ ───► │  RecyclerView │  主界面（搜索/分组/网格）
│ SettingsAct. │ ───► │  设置页        │
└──────┬──────┘      └───────────────┘
       │ 调用
┌──────▼──────┐     ┌──────────────────┐
│   MemeDb    │     │  StoragePaths    │
│  (SQLite)   │     │  路径解析         │
└──────┬──────┘     └──────────────────┘
       │ 写入
┌──────▼──────────────────────────────┐
│  files/cache  files/thumbnails  memes.db │
└──────────────────────────────────────┘
```

```
com.ohmymeme.app/
├── MainActivity.kt     # 主界面：导入/刷新/搜索/网格
├── SettingsActivity.kt # 设置页：读写配置
├── ChipAdapter.kt      # 分组胶囊适配器
├── MemeGridAdapter.kt  # 表情网格适配器（异步加载缩略图 / GIF 动图播放）
├── Meme.kt             # 数据模型（对应 memes 表）
├── MemeDb.kt           # SQLite 封装（7 表 schema 与桌面端一致）
├── ConfigStore.kt      # JSON 配置读写 + 密钥加密
├── CryptoUtil.kt       # Android Keystore AES-GCM 加解密
├── StoragePaths.kt     # 数据/缓存/配置路径解析
├── FileUtils.kt        # SHA-256 + 魔数识别扩展名
├── CacheScanner.kt     # 缓存扫描（双重去重）
├── MemeImporter.kt     # SAF 批量导入
├── Thumbnailer.kt      # 缩略图生成
├── CloudSync.kt        # 云端同步（FTP/S3/R2/WebDAV + AI 元数据清单）
├── AiUtil.kt           # OpenAI 兼容 AI 整理、生图、编辑与找图
└── UpdateChecker.kt    # 版本更新检查（GitHub Releases API + 镜像下载）
```

## 实现要点

### 存储结构对齐桌面端
- 数据库 schema（表/列/索引）逐字段照搬 `src/database.py`，含 `stego_of_hash`/`from_stego` 等隐写兼容字段，桌面端 `memes.db` 可被安卓端直接打开
- 导入重命名规则一致：`{sha256 前16位}{魔数识别扩展名}`
- 缩略图命名一致：`{meme_id}_{size}.png`

### 缓存去重
扫描缓存目录时**双重去重**：按文件名查 DB 防止每次启动重复注册，按 SHA-256 哈希查 DB 防止同图不同名重复。导入（SAF）同样有哈希去重。跳过 `thumbnails` 路径，跳过与同名 `.webp` 共存的 `.gif`（动图生成物）。

### 魔数识别扩展名
`FileUtils.detectExt` 读取文件头魔数识别真实扩展名（QQ 保存常为 .jpg 实为 png/webp），支持 PNG/JPEG/GIF/WebP/BMP，与桌面端 `adb_util._QQ_FILE_TYPES` 一致。

### 配置加密
桌面端用 Fernet，安卓端用 Android Keystore AES-GCM：`CryptoUtil` 生成硬件背书密钥，加密 `config.json` 中的同步凭据及 `ai_chat_api_key`、`ai_image_api_key` 后落盘，读取时自动解密。两端密文格式不同，但字段名和明文语义一致。

### 线程模型
数据库操作在单线程 Executor 中执行（`MemeDb` 内部由 SQLite WAL + Android 锁保证并发安全），UI 更新通过 `runOnUiThread` 回主线程，避免卡顿。

## 技术栈

| 模块 | 技术 | 理由 |
|------|------|------|
| 语言 | Kotlin | 安卓官方 |
| UI | AppCompat + RecyclerView + ConstraintLayout | 轻量原生视图 |
| 数据库 | SQLite (WAL) | 内置，与桌面端 schema 一致 |
| 加密 | Android Keystore (AES-GCM) | 硬件背书密钥 |
| 导入 | Storage Access Framework | 免存储权限批量选图 |
| 构建 | AGP 9.0 + Gradle 9.1 | 版本目录（libs.versions.toml）管理依赖 |

## 许可证

GPL-3.0
