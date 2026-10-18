# OhMyMeme 隐私策略 / Privacy Policy

最后更新 / Last updated：2026-10-18

本文件同时用作 Microsoft Store 上架所需的「隐私策略 URL」

---

## 中文

### 1. 概述

OhMyMeme（下称「本应用」）是一款在您的本机运行的表情包管理与同步工具。开发者**不运营任何用于收集用户数据的服务器**，本应用不设账号体系，不接入统计、埋点或崩溃上报服务。本应用不收集、不上传您的个人信息。

### 2. 收集的信息

无。本应用不收集姓名、邮箱、电话、位置、设备标识等任何可识别个人身份的信息。

### 3. 数据存储位置

- 配置：Windows `%APPDATA%\OhMyMeme\config.json`（macOS/Linux 为对应配置目录）
- 数据：数据库、原图、缩略图、同步索引等，Windows 位于 `%LOCALAPPDATA%\OhMyMeme\`
- 全部数据仅保存在您的本机；云端同步所需的密码等敏感字段经加密（AES/Fernet）后落盘
- 卸载应用不会自动删除这些文件，您可自行删除上述目录以彻底清除数据

### 4. 本应用会主动发起的网络连接

仅在您主动使用相应功能时发起，除「云端同步」外均不发送您的个人数据：

| 场景 | 目标域名 | 用途 / 发送内容 |
| --- | --- | --- |
| 检查更新 | `api.github.com`、`github.com` 及镜像 `github.dpik.top`、`gh.dpik.top`、`gh-proxy.org` | 读取最新版本号；仅常规 HTTP 请求（含 IP），不含个人数据 |
| 云端同步（需您自行配置） | 您自己的 FTP / S3 / R2 / WebDAV 服务器 | 上传/下载您的表情包与索引，直接发往**您本人**的存储服务 |
| 抖音导入 | `douyin.com` 等抖音域名 | 携带您自行提供的 Cookie 拉取您的自定义表情（Cookie 仅发往抖音） |
| 微信表情导入 | 微信 CDN `vweixinf.tc.qq.com`、`wxapp.tc.qq.com` | 下载您的收藏表情图片 |
| 手机版 QQ 导入 | `googledownloads.cn` | 下载 ADB 工具，用于读取您手机上的 QQ 收藏表情 |
| 设置页「关于」 | `contributor.starsfire.top` | 拉取贡献者头像用于展示 |
| 电脑版 QQ（QQNT）导入 | `uapis.cn` | 查询您的 QQ 昵称用于展示 |

- 除以上地址外，本应用不连接任何其他服务器。
- 局域网互联功能仅在**您自己的设备之间**（同一局域网）经 UDP/TCP 传输，不经过互联网。

### 5. 剪贴板与本地文件

为实现导入/复制表情，本应用会读写系统剪贴板；为导入表情，会读取您指定的本地目录及 Telegram / QQ / 微信的本地缓存文件，以及（微信导入）读取微信进程内存以提取解密密钥。以上操作全部在本机完成，内容不会上传给开发者。

### 6. 插件

本应用支持加载用户自行安装的第三方插件。第三方插件的行为由其作者负责，可能访问网络或读取数据，请仅安装您信任的插件。

### 7. 数据安全

本机敏感配置经加密存储。开发者无法访问您的任何本机数据。

### 8. 您的选择与权利

不使用云端同步与各类导入功能时，本应用不产生任何对外数据。您可随时关闭相关功能，或删除本机数据目录以清除全部数据。

### 9. 儿童隐私

本应用不面向 13 岁以下儿童，也不收集任何个人信息。

### 10. 变更与联系方式

本策略如有更新将随版本在项目仓库中更新并注明日期。

联系方式：[Issues · OhMyMeme/OhMyMeme](https://github.com/OhMyMeme/OhMyMeme/issues)

---

## English

### Overview

OhMyMeme is a local-first sticker/meme manager that runs entirely on your device. The developer operates **no server that collects user data**; there is no account system, no analytics, no telemetry, and no crash reporting. All user data (config, database, images, thumbnails, index) is stored **only on your own device**; sensitive fields such as cloud-sync passwords are encrypted at rest (AES/Fernet).

### Network connections

Connections are made only when you actively use a feature: (1) update check against `api.github.com` / `github.com` and mirrors `github.dpik.top`, `gh.dpik.top`, `gh-proxy.org` — version number only; (2) cloud sync to **your own** FTP / S3 / R2 / WebDAV server; (3) Douyin import (`douyin.com`) using the cookie you provide; (4) WeChat sticker import from the WeChat CDN (`vweixinf.tc.qq.com`, `wxapp.tc.qq.com`); (5) mobile QQ import downloads ADB from `googledownloads.cn`; (6) the About page fetches contributor avatars from `contributor.starsfire.top`; (7) QQNT import queries `uapis.cn` for your QQ nickname. LAN sync transfers data only between your own devices on the local network and never over the internet.

### Clipboard and local files

Clipboard access and local-file reads (including reading WeChat process memory to extract the database key) are used solely for import/copy and never leave your device.

### Plugins

Third-party plugins are user-installed; their behavior is the responsibility of their authors. Install only plugins you trust.

### Children

This application is not directed to children under 13 and collects no personal information.

### Contact

[Issues · OhMyMeme/OhMyMeme](https://github.com/OhMyMeme/OhMyMeme/issues)
