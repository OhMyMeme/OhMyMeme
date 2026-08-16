# v0.7.0（暂未命名）

## 变更

- **启动动画遮罩背景色改为写死** — 遮罩背景色写死为 `#000000`（OhMyMeme.mp4 边框纯黑），经 `get_init_data` 传给前端应用到启动遮罩与 html/body 背景，消除动画边缘与窗口背景色差；移除运行时 ffmpeg 抽帧采样，避免影响启动速度
- **设置页导入改为来源列表** — 导入分组整理为 `[icon] [name]` 一行行形式（硬编码 SVG 图标 + 名称），点击对应行弹出该软件的导入对话框；QQ/QQNT 直接开始，Telegram/抖音/微信先弹配置对话框（目录/Cookie/账号等）再开始，配置字段随弹窗展示，进度在对话框内切换

# v0.6.1 — Vue 3 主窗口重构 / 启动动画 / 源码自动编译前端

## 新增

- **主窗口重构为 Vue 3 组件化架构** — `src/vue-src/`（Vite 构建 IIFE 单文件 `src/webui/dist/ohmymeme.js`）：网格/标签栏/分组树/标题栏/拖拽排序/右键菜单等组件化，`useMemes` 集中状态管理，`useDragSort`/`useContextMenu`/`useCollectionBuilder` composables，Pager/TagEditor/ImportMenu/SyncOverlay 等组件（#60）
- **启动动画** — 主窗口启动时全屏播放 `src/resources/OhMyMeme.mp4`（视频结束或 6s 兜底后 0.4s 淡出），仅启动时播放一次，快捷键/托盘呼出不重播；Bottle 新增 `/resources/<filepath:path>` 路由提供内置资源
- **显示启动动画开关** — 设置页「显示启动动画」开关（配置键 `show_startup_animation`，默认开）：开启时动画播放期间即并行加载后续内容（无 300ms 延时，动画天然覆盖桥接稳定时间）；关闭时不播放视频，降级为 300ms 延时后加载
- **动画背景自动贴合视频边框** — `webui.py` 的 `startup_bg_color()` 用 ffmpeg 抽视频首帧 + PIL 采样四边众数色（缓存一次，无 ffmpeg/失败回退 `#0d0d0f`），经 `get_init_data` 传给前端应用到启动遮罩与 html/body 背景，消除动画边缘与窗口背景色差
- **源码运行自动编译前端** — `main.py` 启动时 `_ensure_vue_frontend()` 检查构建产物，缺失（源码运行且未打包）则用 `npx vite build` 自动编译一次，失败仅告警不阻断启动
- **侧边栏折叠按钮移到搜索框内** — `.sidebar-toggle` 位于 `#search-wrap` 左侧，搜索框 `flex:1` 随侧边栏 180px↔48px 动态伸缩

## 变更

- **PyInstaller 打包内置资源** — `build.py` 新增 `--add-data src/resources`，启动动画 mp4 随安装包分发
- **构建自动编译 Vue 前端** — `build.py` 打包前检查 `src/webui/dist/ohmymeme.js`（被 gitignore，CI 全新检出缺失），缺失时自动 `npm ci` → `npx vite build`，失败中止构建；CI 打包不再缺失前端产物

## 修复

- **原生拖拽拖回误触发导入** — Vue 重构后 `nativeDragActive` 从未置 true，原生拖拽进行中回拖到窗口被 drop 处理器误判为导入；现于 `pointermove` 位移 >8px 触发原生拖拽前置 true、Promise `.then/.catch` 中重置，拖拽期间回拖视为取消
- **拖拽失败 toast** — 原生拖拽返回 False（文件缺失/取消）时提示「拖拽失败：本地文件不存在」

# v0.6.0 — 标签系统 / 侧边栏分组树 / 翻页浏览 / Nightly 构建

## 新增

- **表情标签系统** — 右键表情「打标签」弹出标签编辑器：点选已有标签、搜索过滤、输入新建（回车添加），覆盖式写入并自动清理无引用孤儿标签；标签栏横排展示，多标签交集筛选（#29 #47）
- **侧边栏分组树** — 左侧可折叠分组树（支持嵌套分组展开/收起，选中父分组递归包含子分组），搜索栏回归顶部，网格固定 4 列，支持拖拽表情到子分组文件夹卡（#51）
- **未分类分组** — 动态展示未加入任何分组的表情（`collection_id=-4`，不写入 DB/manifest），设置页可开关显示
- **Telegram 缓存导入** — 从 Telegram Desktop `tdata` 解密 AES-IGE/CTR 缓存提取贴纸，webm 无损转动画 webp（libvpx 保留透明通道），动画版与静态版去重，支持本地密码与手动指定目录（#33）
- **微信表情包导入** — 独立 C++ 二进制 `wechat_keyfinder` 内存取证提取密钥 + AES-256-CBC 解密 DB + CDN 下载入库，掩码恢复为主路径无需 RVA，WAL 合并，仅 Windows
- **拖拽排序视觉反馈** — 排序态卡片 `scale(0.95)` + 描边 + 3px 偏移 + 独立 `rotate` 轻微晃动；正在拖拽卡用 `translate(...) scale(0.90)`；FLIP 让位动画与指针捕获（#53 #54）
- **快捷键会话自动隐藏** — 全局快捷键呼出主窗口后，成功复制或成功原生拖拽才自动隐藏（#52）
- **按鼠标显示器显示主窗口** — Windows 全局快捷键呼出时，按鼠标所在显示器工作区就近放置窗口（#46）
- **分页翻页条** — 主窗口单页固定展示（`MEME_PAGE=200`），网格底部渲染翻页按钮（`<` 上一页 / 页码窗口含 `…` / `>` 下一页 / `>>` 末页），搜索/标签/分组切换自动回第 1 页
- **点击分组名返回首页** — 点击当前所在分组名直接回到全部表情视图
- **导入大小与分辨率上限** — 超过 `_IMPORT_MAX_PX`（2560px 最长边）/ `_IMPORT_MAX_BYTES`（20MiB）的文件拒绝接收并计数提示（#32）
- **ADB 存储卷自动识别** — QQ 缓存目录定位回退链支持枚举 `/storage/` 下多存储卷（TF 卡）（#31）
- **快捷键呼出聚焦搜索栏** — 主窗口弹出后自动聚焦搜索框
- **Nightly 非正式版构建** — `nightly.yml` 每日定时 + 手动触发，从 `dev` 分支以版本号 `nightly` 构建 Windows/Linux/macOS 三平台安装包并以 prerelease 发布，更新检查绝不会指向该版本
- **macOS 构建支持** — `build.py --macos` 生成 `.app`（PyInstaller `--windowed` + iconutil 从 icon.png 生成 icns）与 `.dmg`（hdiutil）；`build.yml` 新增 `build-macos` job；更新检查支持 `.dmg` 资产，安装走 `hdiutil attach` + `ditto` 复制到 `/Applications`
- **macOS 双架构构建** — dmg 文件名带架构后缀 `OhMyMeme-v{version}-{arch}.dmg`，`--arch` 指定 arm64/x86_64（默认自动检测）；`build.yml`/`nightly.yml` 矩阵双架构（arm64 用 macos-latest，x86_64 用 macos-15-intel）；更新检查按本机架构选取对应 dmg

## 变更

- **默认收起侧边栏并关闭排序** — 新窗口默认折叠分组树、关闭拖拽排序（#56）
- **静态资源强制 MIME** — 规避注册表 `.js` 被改写导致加载动画卡死（#44）
- **S3 后端 OSS 兼容** — boto3 固定 SigV2 签名 + 虚拟主机寻址（#49）
- **更新检查仅限稳定版** — `_parse_release` 跳过 prerelease 与含 `nightly` 的 tag
- **搜索/筛选态拖拽使用** — 搜索、标签筛选时拖拽表情始终走原生文件拖拽（拖出到聊天窗口），不再误触发排序

## 修复

- **原生拖拽拖回误导入/误打开** — 原生拖拽进行中回拖到窗口，drop 处理器忽略并 `preventDefault`（不再弹导入浮层，也不被系统默认程序打开图片）；`DoDragDrop` 返回 `None`（取消）时不触发自动隐藏
- **Linux 端排序开关按钮点击无效** — `.icon-btn` 内 SVG `pointer-events:none` + `addEventListener` 回退 + 标题栏 mousedown 排除按钮区（#57）
- **局域网虚拟网卡发现回包错接口** — UDP 发现单播回包钉在广播到达接口（Linux `IP_PKTINFO` / Windows `IP_UNICAST_IF`）（#48）
- **QQNT 手动路径重定向** — 环境探测成功时仍保留「选择配置文件/用户数据目录」入口，应对多用户 Windows（#30）
- **分页空页回退** — 删除/搜索后当前页无数据时自动回退到可用末页
- **macOS 运行崩溃/秒退** — pystray 在 macOS 需主线程抢占 NSApplication runloop，与 pywebview 主循环冲突（导致段错误或 `webview.start()` 立即返回），macOS 与 Linux 一样跳过系统托盘；`keyboard` 库 darwin 后端需 root 权限（`Error 13`），macOS 直接改用 pynput（CGEventTap）

# v0.5.2 — 局域网互联（紧急修复）

## 新增

- **局域网互联（电脑端服务）** — 与同一局域网内的手机版 OhMyMeme 配对，互相同步表情包与配置（`lan.py`）。UDP 广播发现（响应不含密钥）→ TCP 握手（HMAC-SHA256 证明，3 次错误断开）→ AES-GCM 加密会话；命令包括 `pull_manifest`/`push_manifest`/`pull_file`/`push_file`/`get_config`/`send_config`/`device_info`；设置页可配置端口与连接密钥，开关仅临时生效不落盘，`lan_secret` 加密存储
- **设备连接确认** — 手机端握手后发送 `device_info` 帧，电脑端弹窗展示设备信息（名称/型号/系统/版本），用户允许/拒绝后回 `{ok, approved, allow_secret_config}`；未确认期间其他命令挂起（超时 60s 拒绝）；`allow_secret_config` 供手机端动态显示密钥拉取/推送按钮
- **允许密钥传输开关（仅内存）** — 设置页「允许密钥传输」勾选，开启前弹窗警示「请勿在公共网络或不信任的网络进行此操作！」；默认关闭，配置同步（`get_config`/`send_config`）剔除 FTP/S3/R2/WebDAV 密码字段，开启后包含密钥字段
- **局域网互联文件安全（与手机端对称）** — `push_file` 四重校验：文件名安全、字节 ≤64MB、可选 `sha256` 一致、图片可解码且宽高 > 0；不合法字节绝不落盘，杜绝孤儿缓存文件
- **局域网互联测试** — `tests/test_lan.py` 回环覆盖 UDP 发现、握手成功/失败/重试上限、加密帧、manifest 交换、文件 push/pull 去重、四重校验（坏哈希/非图片/超限/非法文件名）、配置双向同步（含/不含密钥）、设备确认（允许/拒绝/无回调放行）

## 修复

- **窗口未能正常置顶**
- **排序未能上传云端**
- **局域网安全收紧** — 手机端同步修配套：`push_file` 四重校验杜绝不合法字节落盘（防止恶意/损坏文件写入缓存并入库）

# v0.5.0 — WebDAV 同步 / 拖拽到聊天窗口 / 添加分组弹窗 / GIF 隐写

## 新增

- **WebDAV 同步后端** — 在 FTP/S3/R2 之外新增第四种云端同步后端（WebDAV，兼容 Nextcloud 等），设置页可配置 URL/账号密码/根路径
- **拖拽到聊天窗口** — 表情包可直接拖拽到 QQ/微信/桌面等外部应用（WinForms `DoDragDrop` + CF_HDROP 原生文件拖拽，`native_drag.py` 懒加载 pythonnet；替代失效的 HTML5 拖拽方案）
- **添加分组弹窗** — 标题栏新增「添加分组」按钮，弹窗内输入分组名（支持选择已有分组）、搜索表情、两栏列表间移动并带 FLIP 动画、右侧拖拽排序后一键保存
- **复制处理模式** — 设置页「复制处理」下拉（0 不处理 / 1 webp 缩放 / 2 转 gif / 3 转 gif 隐写原图），复制超大静态图自动缩放到限制内；旧配置自动迁移
- **GIF 增量隐写（实验性）** — 复制模式 3 生成携带无损原图的隐写 GIF（`gif_stego.py`），支持 encode/decode/CLI；导入含 `STG3` 标记的 GIF 自动解码还原原图入库（`from_stego=1`），载体不入库
- **QQNT 电脑端表情提取** — 从电脑版 QQ 收藏目录（`nt_qq/nt_data/Emoji/personal_emoji/Ori`）提取表情，支持 INI 定位、昵称获取、逐文件容错复制与魔数扩展名修正（`qqnt_extract.py`，GPL-3.0 衍生）（来源于[[香草味的纳西妲](https://github.com/VanillaNahida)]）
- **日志导出** — 日志内存缓冲（上限 5000 条），设置页可导出当前运行日志，便于排查问题
- **分组拖拽排序** — 分组/子分组内成员支持拖拽排序（`meme_collections.sort_order`），从最近使用删除、清空最近使用右键菜单项
- **分组右键菜单** — 右键分组可执行更多管理操作
- **更新内容显示** — 更新弹窗展示 GitHub Release 更新说明（支持 Markdown 渲染）
- **push 动态维护远端 manifest** — push 过程中每 5s 用「远端已有 + 本次已确认」快照增量更新远端 manifest，部分失败中断前也上传快照，杜绝远端有文件无有效清单
- **孤儿清理互斥与进度** — 远端孤儿文件删除前非阻塞获取互斥锁（同步进行中拒绝并发删除），删除过程复用进度条展示
- **导入文件自动检测** — 导入时按文件头魔数识别真实扩展名（QQ 保存常为 .jpg 实为 png/webp），GIF 隐写解码判定同步改为魔数检测
- **Linux 打包** — `build.yml` 新增 `build-linux` job，`build.py --package` 支持 AppImage/deb/rpm

## 变更

- **开源协议 MIT → GPL-3.0** — 因引入 GPL-3.0 衍生代码（QQNT 提取模块）改为 GPL-3.0
- **仓库迁移至 [OhMyMeme/OhMyMeme](https://github.com/OhMyMeme/OhMyMeme)** — 更新 README、安装脚本、更新器、setup.py 中地址
- **前端代码拆分重构** — `index.html`/`settings.html` 内联 CSS/JS 拆分为独立文件（`index.css`/`index.js`/`settings.css`/`settings.js`），拖拽排序重写为事件委托 + Pointer Events + 指针捕获 + FLIP 动画，模型驱动（#24）
- **复制逻辑解耦** — 图片修饰（缩放/转格式/隐写）与复制到剪贴板分离为不同函数；复制模式配置保存方式调整
- **导入行为调整** — 导入流程与 UI 细节优化
- **GitHub Actions** — build job 拆分为 `build-windows` / `build-linux` 两个任务

## 修复

- **Ctrl 按键异常** — 全局快捷键 `suppress=True` 会安装 `WH_KEYBOARD_LL` 状态机吞掉按键事件，改为 `suppress=False`（#23）
- **旧库 stego_of_hash 启动崩溃** — 旧数据库缺 `stego_of_hash` 列时 `CREATE INDEX` 抛 OperationalError 中断启动，索引创建移到迁移之后（#23）
- **WebDAV 同步加固** — 失败项显示 / 互斥锁 / 中断清理 / 远端孤儿 GC（#22）
- **Windows 窗口拖拽抖动** — 增量回退改用 `screenX/screenY`（`clientX/clientY` 是相对坐标，窗口滞后位移被当作反向增量回传形成反馈振荡）（#18）
- **Linux 无边框窗口无法拖动** — 改用合成器原生拖动（`begin_move_drag` + `Gdk.CURRENT_TIME`），Wayland 下 `w.move()` 无效（#15 #16）
- **右键菜单超出窗口边框** — 窗口边缘弹出时自动换向，避免菜单溢出无法使用（#17）
- **Linux 更新问题** — AppImage 资产选取、无 `/dev/fuse` 时 `--appimage-extract-and-run` 回退、下载文件名规范化
- **安装时文件占用** — 更新器启动安装程序前自动退出应用，避免 exe 文件锁

## 特别鸣谢

### 代码贡献

- [Ze514](https://github.com/Ze514) — QQNT 电脑端表情提取（#14）、WebDAV 同步后端

- [LorienYang](https://github.com/LorienYang) — 拖拽排序修复、WebUI 重构协作

- [lateworker](https://github.com/lateworker) — 同步后端与测试协作

  [QQ电脑版表情包导出模块](https://github.com/VanillaNahida/QQFavoriteExtract)来源于[[香草味的纳西妲](https://github.com/VanillaNahida)]

# v0.4.1 — WebP 动图 / 浏览器拖入导入 / 核显优化

## 新增

- **WebP 动图支持** — 导入、存储、网格展示动画 WebP，剪贴板直接传送 WebP 原文件（CF_HDROP + 自定义 "WebP" 格式 + CF_DIB 回退），QQ/微信原生解码，保留动画与透明
- **浏览器图片拖入导入** — 从浏览器直接拖拽图片到窗口即可导入，自动去掉 URL `@` 修饰参数，修正扩展名识别与 Base64 编码
- **浏览器来源尝试获取原图** — 设置页新增开关，开启后从来源 URL 下载原图导入（无扩展名时按 Content-Type 推断），附网络连通性实时检测
- **每日自动检测更新** — 每 24 小时静默检查一次更新，复用启动时的检测与弹窗逻辑
- **从最近使用中删除** — 右键最近使用列表中的表情包可单独移除
- **`--debug` 启动参数** — 输出全部 DEBUG 级别日志，便于排查

## 变更

- **核显优化** — 新增 `is_integrated_gpu()`（DXGI 检测主 GPU 专用显存 < 1GB 视为核显）；核显机器禁用 WebView2 GPU 合成（`--disable-gpu-compositing`），内存占用从 800MB 降至 120MB；独显保持完整硬件加速
- **S3 上传重构** — 改用 presigned URL + `urllib` 替代 boto3 `put_object`，避免 chunked 编码污染上传文件
- **托盘菜单英文化** — Show/Hide、Quit（原为中文）
- **CI 拆分** — 独立 `check.yml`（lint+test）与 `build.yml`（Windows 打包），build 通过 `workflow_run` 在 check 通过后触发
- **Linux 托盘判断** — 由 `is_wsl()` 改为 `platform.system() == "Linux"` 决定是否跳过系统托盘

## 修复

- **更新时软件未正常退出** — `shutdown()` 末尾 `os._exit(0)` 强制退出，清理残留非 daemon 线程（updater 线程池）
- **平铺窗口管理器启动崩溃** — `window_x`/`window_y` 为 null 时不再抛 TypeError（#8）
- **S3 同步检测失效** — `file_exists` 增加 `get_object` 回退，修复 `head_object` 误报 404（#7）
- **拖拽排序真正生效** — 重写拖拽换位逻辑，修复 v0.4.0 遗留的拖拽排序 Bug
- **浏览器拖拽图片导入异常** — 修正文件扩展名识别错误与 Base64 编码不正确问题
- **ADB 路径拼接** — 修复路径拼接错误（#5）

- ## 特别鸣谢

  ### 代码贡献

  - [[Ze514](https://github.com/Ze514)] — 拖拽排序（#12）、WebP 剪贴板（#11）、WebP 存储（#9）、浏览器拖拽导入（#6）、浏览器原图下载（#3）
  - [[LorienYang](https://github.com/LorienYang)] — S3 上传与同步检测修复（#7）
  - [[RainLuohua](https://github.com/RainLuohua)] — 平铺窗口管理器启动崩溃修复（#10）
  - [[oralrinse](https://github.com/oralrinse)] — ADB 路径拼接修复（#5）

  ### Issue 反馈

  - [[Chiclats](https://github.com/Chiclats)] — 反馈平铺窗口管理器 (Niri) 下启动崩溃（#8）
  - [[ylhcqN](https://github.com/ylhcqN)] — 反馈 Linux 原生环境（非 WSL）GTK 线程冲突（#2）
  - [[LorienYang](https://github.com/LorienYang)] — 反馈 FTP/S3 同步状态显示异常（#1）
  - [[oralrinse](https://github.com/oralrinse)] — 反馈 Win11 ADB 检测 0% 卡死及 TypeError（#4）

  ### 还有各位群友们及B友们

  ### 还有[QQ电脑版表情包导出模块](https://github.com/VanillaNahida/QQFavoriteExtract)贡献者[[香草味的纳西妲](https://github.com/VanillaNahida)]

# v0.4.0 — 自定义排序 / 多级分组 / 最近使用

## 新增

- **表情包自定义排序** — 拖拽网格中的表情包即可调整顺序，自动保存到 manifest（version 3），支持丝滑 CSS transition 动画
- **多级分组** — 分组支持嵌套（最多 3 层），右键大分组空白区域新建子分组；分组以文件夹卡片形式展现在网格中，点击进入子分组；分组 tab 按层级展开
- **右键"加入分组"** — 右键表情包 → 加入分组 → 弹窗列出当前大分组下的所有子分组，支持新建分组后直接加入
- **"最近使用"默认分组** — 自动收录使用过的表情包，按使用先后排列（最近使用的排最前），复制表情包时自动记录并刷新排序

## 变更

- **manifest 格式升级** — version 2 → version 3，分组支持嵌套结构（`children` 字段），启动时自动转换旧版 manifest
- **搜索排序** — 默认按 `sort_order ASC, updated_at DESC` 排列

## 修复

- **manifest 空分组自动清理** — 嵌套场景下递归删除空分组
- **WebP 动图不再转 GIF** — 直接向剪贴板传送 WebP 原文件（`_copy_webp_windows`：CF_HDROP + 自定义 "WebP" 格式 + CF_DIB 回退），QQ/微信原生解码 WebP，保留动画与透明，避免 GIF 转换带来的黑底/残影问题；移除 `_webp_to_gif` 相关逻辑

## 已知问题

- **拖拽排序仍有 Bug** — 自定义排序功能已开发，但在 pywebview 环境下拖拽交互不稳定，部分场景下表情包拖拽后显示异常，后续版本修复

# v0.3.6 — 设置页版本显示不阻塞 / 新增镜像源

## 新增

- **新增 GitHub 镜像源** — 提高更新检查和下载的可用性

## 修复

- **打开设置页卡顿** — `initVersion` 原调用 `check_update()`（含网络 I/O），改为 `get_current_version()` 直接返回本地版本号，秒开

# v0.3.5 — ADB 路径迁移 / 更新检查优化

## 修复

- **ADB 下载权限问题** — 安装版（Program Files）下无法写入 `.adb` 目录，现改为存放在 `%LOCALAPPDATA%/OhMyMeme/.adb`；启动时自动检测旧版（exe 目录）`.adb` 并迁移至新位置，迁移后清理旧目录
- **更新检查错误提示不友好** — 设置页检查更新时若全部镜像和直连均失败，原返回原始 Python 异常（如 `URLError[WinError 10061]`），现改为显示"无法连接到 GitHub，请检查网络设置"

# v0.3.4 — 导入菜单 / 剪贴板导入 / 同步状态检查 / 删除修复

## 新增

- **导入菜单** — 点击"导入"弹出三个选项：本地导入、从剪贴板导入、从手机版 QQ 缓存获取
- **从剪贴板导入** — 读取系统剪贴板中的图片并导入，支持导入后重命名
- **同步状态检查** — 设置页云端同步部分新增"检查同步状态"按钮，显示本地/云端数量差异

## 修复

- **删除本地所有表情包** — 修复 `build_manifest` 导入错误（`from .manifest import build_manifest` → `from .manifest import build as build_manifest`），删除后自动刷新主窗口
- **剪贴板导入→文件列表时重命名异常** — 文件路径来源的导入未返回正确 ID 和 `original_name`，重命名弹窗显示空值；`_do_import` 改为返回导入的 ID 列表，`import_from_clipboard` 据此查询原文件名，回退为"未命名"
- **移除源码运行场景下的开机自启清理逻辑** — 防止误删发行版注册的开机自启项；现在仅打包版本（`frozen`）处理开机自启同步

# v0.3.3 — Bugfix: 收藏夹清空后自动返回主页

## 修复

- 在收藏夹中取消收藏最后一个表情包后，自动返回全部视图而非停留在空收藏夹

# v0.3.2 — 默认快捷键更改 + ESC 关闭窗口

## 变更

- 默认快捷键 `Ctrl+Alt+M` → `Ctrl+Alt+N`（避免与网易云音乐冲突）
- 主页按 ESC 关闭窗口
- 设置页按 ESC 关闭窗口（已有，补充说明）

# v0.3.1 — Bugfix: 构建/弹窗/取消导入

## 修复

- **adb-help.txt 未打包** — PyInstaller `--add-data` 添加该文件
- **发行版 adb 弹窗** — `_run_adb`/`detect_adb` 在 Windows frozen 模式下使用 `CREATE_NO_WINDOW`
- **取消导入不停止轮询** — 新增 `cancel_qq_import()` + `_QQ_CANCEL` 标志 + `_check_cancel()` 在各关键步骤检查；关闭覆盖层时自动取消

# v0.3.0 — QQ 表情包导入 + ADB 调试日志

## 新增

- **QQ 表情包缓存导入** — 设置页新增"从手机版 QQ 缓存导入"按钮，自动检测/下载 ADB、启动服务、等待设备连接（300s 超时）、`adb pull` 拉取 QQ_Favorite 目录、魔数识别扩展名、打包 ZIP、另存为对话框保存
- **魔数识别** — 支持 PNG/JPEG/GIF/WebP/BMP 无扩展名文件自动补全
- **ADB 带进度下载** — 从 googledownloads.cn 下载 platform-tools，前端实时显示下载百分比
- **进度覆盖层** — 导入过程分阶段显示（下载 ADB→启动服务→等待设备→拉取文件→处理→完成），300ms 轮询
- **帮助按钮** — 等待设备阶段显示"不知道怎么办？"按钮，打开 `adb-help.txt`（含各大品牌开启 USB 调试教程）
- **导入后引导** — ZIP 保存后提示用户筛选文件并一键导入
- **`--debug-adb` 运行时日志** — 开启后所有 adb 命令记录到日志（命令、stdout、stderr、超时）

# v0.2.2

## 云端同步多线程

- push/pull 使用 `ThreadPoolExecutor` 多线程传输
- 配置项 `sync_threads`（默认 3，范围 1-8）
- 每个工作线程创建独立后端连接（FTP/S3/R2 均适用）
- `_sync_lock` 保护进度状态原子递增

## 安装更新前自动退出应用

- `run_downloaded_installer()` 启动安装程序后调用 `_schedule_quit()` 关闭窗口
- 避免 exe 文件锁导致更新失败

## 开机自启修复

- 设置页开关现在正确读取真实系统状态（不再是 undefined）
- `is_auto_start_enabled()` 改为仅检测注册表 Run 键（移除启动文件夹快捷方式检测）
- `set_auto_start()` 仅操作注册表，不再创建/删除启动文件夹快捷方式
- InnoSetup 安装程序改为写注册表 Run 键，不再创建启动文件夹快捷方式
- `[InstallDelete]` 升级时自动清理旧版遗留的启动快捷方式
- 源码运行时仅清理指向 python.exe 的注册项，不误删发行版

## 启动参数

- `--startup-debug`: 输出开机自启检测详情（注册表值、启动文件夹路径、快捷方式是否存在）
- `--silent` 在源码启动时忽略配置文件的 `silent_start`（需显式传参）

## OhMyMeme v0.2.1 更新日志

### 新功能

- **静默启动** — 开机自启时可静默托盘启动
- **同步进度条** — 上传/下载实时显示进度百分比、速度、当前文件名，支持"后台运行"关闭弹窗，完成后弹窗显示结果
- **进度显示设置** — 设置页新增 4 个开关：上传进度条 / 上传完毕提示 / 下载进度条 / 下载完毕提示
- **危险操作区** — 设置页底部新增"删除本地所有表情包"和"删除云端所有表情包"，需双输入框均输入 `confirm` 才可执行
- **配置版本追踪** — config.json 新增 `version` 字段，`0.2.0` → `0.2.1` 自动迁移，清理残留的 `window_width`/`window_height`

### Bug 修复

- **拖入导入** — pywebview 6.2.1 无 `on_drop` API（旧代码被 `try/except` 吞掉从未生效），重写为 JS File API + base64 → Bottle `/api/upload/`
- **导入按钮** — `file_types` 格式修正（混入了描述文字导致过滤异常）
- **窗口高度无效** — 配置中残留旧值覆盖了默认值，现改为硬编码 700×500，停止存储窗口尺寸
- **右键菜单溢出** — 超出窗口右沿时自动向左偏移
- **重命名** — 原来会改磁盘文件名（引起各种副作用），改为只改 DB `original_name`（显示名）
- **远端下载显示名** — sync pull 时未从 manifest 读取 `name` 字段，下载后丢失原文件名
- **导入临时文件残留** — `_upload_` 临时文件在导入完成后自动删除

### 代码清理

- 移除 `_on_drop` 死代码（pywebview 6.2.1 Windows CEF 不支持）
- 项目文档：更新 `AGENTS.md`

## **v0.2.0**

增加更新功能
AI优化加载速度及用户体验
目前Nuitka打包360也反馈了，但安全起见暂时还是使用pyinstaller

<img width="1099" height="904" alt="35ee4a78-bd22-4401-88c1-a727fcd03b70" src="https://github.com/user-attachments/assets/417e5ddf-6571-4ff5-bc39-671cf1f950e7" />

## **v0.1.1 当前版本不会报毒**

Nuitka打包会被很多杀毒软件杀死，正在与厂商协商ing...（目前**微软、火绒**已解决该问题）， 临时使用pyinstaller代替nuitka
Linux正在做适配ing...

<img width="1744" height="708" alt="QQ20260726-182501" src="https://github.com/user-attachments/assets/c00c7118-1d57-4e81-9adc-3fa5d7159b72" />
<img width="1734" height="1056" alt="32C4CE62@056A0E0(07-26-18-11-43)" src="https://github.com/user-attachments/assets/aef2e533-d554-4945-a193-8c66441dbeaa" />

## OhMyMeme v0.1.0

轻量化跨平台表情包管理系统 — 突破表情包上限，快捷键呼出、搜索即复制。

------

### 功能

- **系统托盘运行** — 最小化资源占用，后台常驻
- **全局快捷键** — 默认 `Ctrl+Alt+M` 呼出/隐藏主面板
- **表情管理** — 导入/搜索/标签分类/收藏/自定义分组
- **一键复制** — 点击表情包自动复制到剪贴板（GIF 保留动画）
- **拖放导入** — 直接拖拽图片到窗口即可导入
- **右键菜单** — 重命名/收藏/添加分组/从分组移除/删除
- **GIF 动图** — 网格内自动播放，可在设置中关闭
- **分组筛选** — 按收藏夹或自定义分组过滤，点击标签+分组叠加搜索
- **本地缓存** — 缩略图+原图双层缓存，离线可用
- **缓存扫描** — 启动时自动扫描缓存目录，已有文件无需重复导入
- **远程同步** — 支持 FTP / S3 / R2 三种后端，多设备同步
- **无边框窗口** — 自定义标题栏，鼠标拖拽移动

### 安装注意事项

> ⚠️ **火绒** 和 **Microsoft Defender** 可能会将编译后的 exe 误报为病毒。如遇拦截，请添加到信任区。正准备向各厂商提交误报申诉，后续版本会逐步解决。