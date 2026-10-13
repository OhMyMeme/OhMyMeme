# pyright: basic

"""GitHub 仓库插件导入：归档下载、子树抽取、限额校验与镜像回退。

网络访问只依赖 urllib（无新增依赖），下载器可注入供离线测试。
"""

import io
import json
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from ohmymeme.core.plugins.runtime import seeding
from ohmymeme.core.plugins.runtime.seeding import PluginSeedError, tree_fingerprint

OFFICIAL_REPO = "OhMyMeme/OhMyMeme"

# 与 services/updates.py 的 GitHub 镜像同源；core 层不得反向 import services，故复制常量
GITHUB_MIRRORS = (
    "https://github.dpik.top/",
    "https://gh.dpik.top/",
    "https://gh-proxy.org/",
)

ARCHIVE_MAX_BYTES = 50 * 1024 * 1024
EXTRACT_MAX_BYTES = 20 * 1024 * 1024
EXTRACT_MAX_ENTRIES = 4000
FILE_MAX_BYTES = 10 * 1024 * 1024
DOWNLOAD_TIMEOUT = 30

_USER_AGENT = "OhMyMeme/1.0 (+https://github.com/OhMyMeme/OhMyMeme)"

_ALLOWED_HOSTS = frozenset(
    {
        "github.com",
        "www.github.com",
        "codeload.github.com",
        "objects.githubusercontent.com",
    }
    | {urllib.parse.urlparse(mirror).hostname or "" for mirror in GITHUB_MIRRORS}
)

_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_VERSION_RE = re.compile(r"^v?\d+(?:\.\d+)*$")
_LICENSE_PREFIXES = ("LICENSE", "COPYING", "NOTICE")


class DownloadError(Exception):
    """下载层错误：status 为 HTTP 状态码，网络类错误为 None。"""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


# 解析并归一化仓库标识为 owner/repo
def parse_repo(value):
    text = str(value or "").strip()
    if not text:
        raise PluginSeedError("invalid_repo", "empty repository")
    if "://" in text:
        parsed = urllib.parse.urlparse(text)
        if parsed.hostname not in ("github.com", "www.github.com"):
            raise PluginSeedError("invalid_repo", text)
        segments = [part for part in parsed.path.split("/") if part]
    else:
        segments = [part for part in text.split("/") if part]
        if len(segments) != 2:
            raise PluginSeedError("invalid_repo", text)
    if len(segments) < 2:
        raise PluginSeedError("invalid_repo", text)
    owner, repo = segments[0], segments[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    for segment in (owner, repo):
        if segment in (".", "..") or not _SEGMENT_RE.match(segment):
            raise PluginSeedError("invalid_repo", text)
    return "%s/%s" % (owner, repo)


# 生成要尝试的 ref 路径候选（tag / 分支 / HEAD）
def _ref_candidates(repo, ref, app_version):
    if ref:
        text = str(ref).strip()
        if text:
            if text.upper() == "HEAD":
                return ["HEAD"]
            if text.startswith("refs/"):
                return [text]
            if _VERSION_RE.match(text):
                if text.startswith("v"):
                    return ["refs/tags/%s" % text, text]
                return ["refs/tags/%s" % text, "refs/tags/v%s" % text, text]
            return ["refs/heads/%s" % text, text]
    if repo == OFFICIAL_REPO and app_version:
        return ["refs/tags/v%s" % app_version, "HEAD"]
    return ["HEAD"]


# 由实际命中的 ref 推断 tag（非 tag 返回 None）
def _tag_from(used_ref, original_ref):
    if used_ref.startswith("refs/tags/"):
        return used_ref[len("refs/tags/") :]
    if original_ref and used_ref == original_ref and _VERSION_RE.match(used_ref):
        return used_ref
    return None


# 构造归档下载 URL
def _archive_url(repo, ref):
    return "https://github.com/%s/archive/%s.zip" % (repo, ref)


# 校验主机在白名单内
def _verify_host(url):
    host = urllib.parse.urlparse(url).hostname or ""
    if host not in _ALLOWED_HOSTS:
        raise DownloadError("blocked host: %s" % host, status=None)


# 逐跳校验重定向目标主机
class _RedirectValidator(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _verify_host(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# 流式读取响应并按归档上限中止
def _read_bounded(response, url):
    chunks = []
    total = 0
    while True:
        chunk = response.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > ARCHIVE_MAX_BYTES:
            raise PluginSeedError("too_large", url)
        chunks.append(chunk)
    return b"".join(chunks)


# 默认下载器：urllib + 超时 + 主机/重定向校验
def _default_opener(url):
    _verify_host(url)
    handler = _RedirectValidator()
    opener = urllib.request.build_opener(handler)
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with opener.open(request, timeout=DOWNLOAD_TIMEOUT) as response:
            return _read_bounded(response, url)
    except urllib.error.HTTPError as error:
        raise DownloadError(str(error), status=error.code) from error
    except (urllib.error.URLError, OSError) as error:
        raise DownloadError(str(error), status=None) from error


# 单次下载（注入 opener 时全走注入实现）
def _download(url, opener):
    if opener is not None:
        return opener(url)
    return _default_opener(url)


_ARCHIVE_CACHE = {}
_ARCHIVE_CACHE_TTL = 300.0
_ARCHIVE_CACHE_LIMIT = 3
_ARCHIVE_CACHE_MAX_BYTES = 40 * 1024 * 1024


# 清空归档缓存（测试与内存回收用）
def clear_cache():
    _ARCHIVE_CACHE.clear()


# 读取未过期的归档缓存
def _cache_lookup(url):
    entry = _ARCHIVE_CACHE.get(url)
    if entry is None:
        return None
    stored, data = entry
    if time.monotonic() - stored > _ARCHIVE_CACHE_TTL:
        _ARCHIVE_CACHE.pop(url, None)
        return None
    return data


# 写入归档缓存并按条数上限淘汰最旧项
def _cache_store(url, data):
    if len(data) > _ARCHIVE_CACHE_MAX_BYTES:
        return
    _ARCHIVE_CACHE[url] = (time.monotonic(), data)
    while len(_ARCHIVE_CACHE) > _ARCHIVE_CACHE_LIMIT:
        oldest = min(_ARCHIVE_CACHE, key=lambda key: _ARCHIVE_CACHE[key][0])
        _ARCHIVE_CACHE.pop(oldest, None)


# 直连失败按镜像前缀重试，其余错误分类上抛；成功的归档字节短缓存避免预览与安装重复下载
def _fetch_bytes(url, opener=None):
    cached = _cache_lookup(url)
    if cached is not None:
        if len(cached) > ARCHIVE_MAX_BYTES:
            raise PluginSeedError("too_large", url)
        return cached
    candidates = [url] + [mirror + url for mirror in GITHUB_MIRRORS]
    last_error = None
    for candidate in candidates:
        try:
            data = _download(candidate, opener)
        except DownloadError as error:
            if error.status == 404:
                raise PluginSeedError("not_found", candidate) from error
            if error.status in (403, 429):
                raise PluginSeedError("rate_limited", candidate) from error
            last_error = error
            continue
        if len(data) > ARCHIVE_MAX_BYTES:
            raise PluginSeedError("too_large", candidate)
        _cache_store(url, data)
        return data
    raise PluginSeedError("network", str(last_error) if last_error else url)


# 下载归档：逐个 ref 候选尝试，仅 not_found 时回落
def _download_archive(repo, candidates, opener):
    last_error = None
    for candidate in candidates:
        try:
            return _fetch_bytes(_archive_url(repo, candidate), opener), candidate
        except PluginSeedError as error:
            if error.reason == "not_found":
                last_error = error
                continue
            raise
    if last_error is not None:
        raise last_error
    raise PluginSeedError("not_found", repo)


# 校验单条归档条目是否安全
def _validate_entry(info):
    name = info.filename
    if not name:
        raise PluginSeedError("invalid_package", "empty entry name")
    if name.startswith("/") or name.startswith("\\"):
        raise PluginSeedError("invalid_package", "absolute path")
    if "\\" in name:
        raise PluginSeedError("invalid_package", "backslash path")
    if any(part == ".." for part in name.split("/")):
        raise PluginSeedError("invalid_package", "parent path")
    if (info.external_attr >> 16) & 0xF000 == 0xA000:
        raise PluginSeedError("invalid_package", "symlink entry")
    if info.file_size > FILE_MAX_BYTES:
        raise PluginSeedError("too_large", name)


# 计算解压目标路径并确保不逃出根目录
def _safe_join(root, relative):
    resolved = root.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(resolved):
        raise PluginSeedError("invalid_package", "escape path")
    return target


# 抽取 {顶层}/plugins/{id}/ 子树到临时目录，返回 (临时目录, 顶层目录名)
def _extract_subtree(archive_bytes, plugin_id):
    try:
        archive = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except zipfile.BadZipFile as error:
        raise PluginSeedError("invalid_package", str(error)) from error
    with archive:
        infos = archive.infolist()
        if len(infos) > EXTRACT_MAX_ENTRIES:
            raise PluginSeedError("too_large", "entry count")
        total = 0
        top = ""
        for info in infos:
            _validate_entry(info)
            if not top and info.filename:
                top = info.filename.split("/", 1)[0]
            total += info.file_size
            if total > EXTRACT_MAX_BYTES:
                raise PluginSeedError("too_large", "declared size")
        if not top:
            raise PluginSeedError("layout_mismatch", "empty archive")
        prefix = "%s/plugins/%s/" % (top, plugin_id)
        targets = []
        for info in infos:
            name = info.filename
            if info.is_dir() or not name or not name.startswith(prefix):
                continue
            relative = name[len(prefix) :]
            if not relative or relative.endswith("/"):
                continue
            targets.append((info, relative))
        if not targets:
            raise PluginSeedError("layout_mismatch", "plugins/%s not found" % plugin_id)
        tmp_dir = Path(tempfile.mkdtemp(prefix="ohmymeme-github-"))
        written = 0
        try:
            for info, relative in targets:
                target = _safe_join(tmp_dir, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                data = archive.read(info)
                written += len(data)
                if written > EXTRACT_MAX_BYTES:
                    raise PluginSeedError("too_large", "extracted size")
                target.write_bytes(data)
        except BaseException:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise
    return tmp_dir, top


# 读取子树根 plugin.json
def _read_repo_meta(subtree, plugin_id):
    path = subtree / seeding.PLUGIN_META_FILENAME
    if not path.is_file():
        raise PluginSeedError("layout_mismatch", "missing plugin.json")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PluginSeedError("invalid_package", "invalid plugin.json") from error
    if not isinstance(raw, dict):
        raise PluginSeedError("invalid_package", "plugin.json must be an object")
    if raw.get("id") != plugin_id:
        raise PluginSeedError("identity_mismatch", str(raw.get("id")))
    return raw


# 按 entry 模块名定位包目录（优先 {pkg}/，其次 src/{pkg}/）
def _find_package_dir(subtree, entry):
    if not isinstance(entry, str) or ":" not in entry:
        raise PluginSeedError("invalid_package", "invalid entry")
    module = entry.split(":", 1)[0]
    for candidate in (subtree / module, subtree / "src" / module):
        if candidate.is_dir():
            return candidate
    raise PluginSeedError("layout_mismatch", "package %s not found" % module)


# 收集子树根的许可证类文件绝对路径
def _root_notice_files(subtree):
    paths = []
    for path in sorted(subtree.iterdir()):
        if path.is_file() and path.name.upper().startswith(_LICENSE_PREFIXES):
            paths.append(str(path))
    return paths


# 非 tag 导入的 ref_label（HEAD 取顶层目录 {repo}-{branch} 的 branch 段）
def _ref_label(top, repo, used_ref, original_ref):
    if original_ref:
        return original_ref
    repo_name = repo.split("/")[-1]
    prefix = repo_name + "-"
    if top.startswith(prefix):
        return top[len(prefix) :]
    return top


# 下载并解析仓库内 plugins/{id} 子树，返回安装所需信息
def fetch_plugin(repo, ref, plugin_id, app_version="", opener=None):
    if not isinstance(plugin_id, str) or not plugin_id:
        raise PluginSeedError("invalid_plugin_id", str(plugin_id))
    normalized = parse_repo(repo)
    original_ref = str(ref).strip() if ref else ""
    candidates = _ref_candidates(normalized, original_ref, app_version)
    archive_bytes, used_ref = _download_archive(normalized, candidates, opener)
    tmp_dir = None
    try:
        tmp_dir, top = _extract_subtree(archive_bytes, plugin_id)
        raw = _read_repo_meta(tmp_dir, plugin_id)
        package_dir = _find_package_dir(tmp_dir, raw.get("entry"))
        tag = _tag_from(used_ref, original_ref)
        if tag is not None:
            version = tag[1:] if tag.startswith("v") else tag
            version_key = version
            ref_label = tag
        else:
            ref_label = _ref_label(top, normalized, used_ref, original_ref)
            declared = raw.get("version")
            version = declared if isinstance(declared, str) and declared else ref_label
            version_key = "%s-%s" % (version, tree_fingerprint(package_dir)[:7])
        meta = {
            "id": plugin_id,
            "name": raw.get("name") or plugin_id,
            "entry": raw.get("entry"),
            "package_root": raw.get("package_root") or package_dir.name,
            "version": version,
        }
        # 可选身份字段只在声明的包内保留；第三方包缺省时交给安装校验兜底
        if "api_version" in raw:
            meta["api_version"] = raw.get("api_version")
        if "capabilities" in raw:
            meta["capabilities"] = list(raw.get("capabilities") or ())
        return {
            "repo": normalized,
            "ref": used_ref,
            "ref_label": ref_label,
            "tag": tag,
            "plugin_id": plugin_id,
            "meta": meta,
            "version": version,
            "version_key": version_key,
            "tree_sha256": tree_fingerprint(package_dir),
            "package_dir_src": str(package_dir),
            "license_paths": _root_notice_files(tmp_dir),
            "tmp_dir": str(tmp_dir),
        }
    except BaseException:
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


# 经安装事务落盘 fetch_plugin 结果，返回解析后的版本信息
def install_plugin(data_dir, fetched):
    meta = fetched["meta"]
    package_src = Path(fetched["package_dir_src"])
    package_root = meta.get("package_root") or package_src.name

    def populate(temp_dir):
        shutil.copytree(package_src, Path(temp_dir) / package_root)
        for path_str in fetched.get("license_paths") or ():
            source = Path(path_str)
            if source.is_file():
                shutil.copy2(source, Path(temp_dir) / source.name)

    return seeding.install_prepared(
        data_dir,
        meta,
        populate,
        fetched["version_key"],
        source={
            "type": "github",
            "repo": fetched["repo"],
            "ref": fetched["ref"],
            "tree": fetched["tree_sha256"],
        },
    )


# 清理 fetch_plugin 的临时目录（幂等，忽略错误）
def dispose(fetched):
    tmp_dir = fetched.get("tmp_dir") if isinstance(fetched, dict) else None
    if tmp_dir:
        shutil.rmtree(tmp_dir, ignore_errors=True)
