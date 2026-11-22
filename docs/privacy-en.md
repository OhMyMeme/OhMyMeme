# OhMyMeme Privacy Policy

English（[简体中文](privacy.md)）

Last updated: 2026-10-18

---

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
