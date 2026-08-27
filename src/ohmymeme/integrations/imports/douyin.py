"""抖音表情包下载导入（纯协议驱动 + ABogus 签名 + curl_cffi TLS 指纹）"""

import hashlib
import logging
import os
import random
import string
import tempfile
import threading
import time
from urllib.parse import quote, urlencode

from curl_cffi import requests

from ohmymeme.integrations.imports.abogus import ABogus

logger = logging.getLogger(__name__)

_DOUYIN_STATE = {
    "status": "idle",
    "progress": 0,
    "message": "",
    "error": "",
    "error_code": "",
    "total": 0,
    "done": 0,
    "imported": 0,
    "rejected": 0,
}

_DOUYIN_LOCK = threading.Lock()
_DOUYIN_CANCEL = False
_DOUYIN_JOB_CANCEL = None
_DOUYIN_JOB_SNAPSHOT = None


def _bind_douyin_job(_manager, record, context):
    global _DOUYIN_JOB_CANCEL, _DOUYIN_JOB_SNAPSHOT
    _DOUYIN_JOB_CANCEL = record.cancellation_event
    _DOUYIN_JOB_SNAPSHOT = context.snapshot


API_STICKER = "https://www.douyin.com/aweme/v1/web/im/resource/list/aggregation"
API_TTWID = "https://ttwid.bytedance.com/ttwid/union/register/"
API_SELF = "https://www.douyin.com/aweme/v1/web/user/profile/self/"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/90.0.4430.212 Safari/537.36"
)

HEADERS = {
    "User-Agent": UA,
    "Referer": "https://www.douyin.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def _update_dy(**kw):
    global _DOUYIN_JOB_SNAPSHOT
    with _DOUYIN_LOCK:
        _DOUYIN_STATE.update(**kw)
        snapshot = _DOUYIN_JOB_SNAPSHOT
        state = dict(_DOUYIN_STATE)
    if snapshot is not None:
        snapshot(
            phase=state["message"],
            progress=state["progress"] / 100,
            message=state["message"],
            error_code=state["error_code"],
            error=state["error"],
        )


def get_douyin_progress():
    with _DOUYIN_LOCK:
        return dict(_DOUYIN_STATE)


def cancel_douyin_import():
    global _DOUYIN_CANCEL, _DOUYIN_JOB_CANCEL, _DOUYIN_JOB_SNAPSHOT
    _DOUYIN_CANCEL = True
    if _DOUYIN_JOB_CANCEL is not None:
        _DOUYIN_JOB_CANCEL.set()


def _check_cancel():
    return _DOUYIN_CANCEL or (
        _DOUYIN_JOB_CANCEL is not None and _DOUYIN_JOB_CANCEL.is_set()
    )


def _reset_state():
    global _DOUYIN_CANCEL
    _DOUYIN_CANCEL = False
    _update_dy(
        status="idle",
        progress=0,
        message="",
        error="",
        error_code="",
        total=0,
        done=0,
        imported=0,
        rejected=0,
        download_failed=0,
    )


def _gen_random_str(length: int = 126) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=length))


def _gen_verify_fp() -> str:
    base_str = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    t = len(base_str)
    ms = int(round(time.time() * 1000))
    base36 = ""
    n = ms
    while n > 0:
        rem = n % 36
        base36 = (str(rem) if rem < 10 else chr(ord("a") + rem - 10)) + base36
        n = int(n / 36)

    o = [""] * 36
    o[8] = o[13] = o[18] = o[23] = "_"
    o[14] = "4"

    for i in range(36):
        if not o[i]:
            x = int(random.random() * t)
            if i == 19:
                x = 3 & x | 8
            o[i] = base_str[x]

    return "verify_" + base36 + "_" + "".join(o)


def _sign_url(base_url: str, params: dict, method: str = "GET") -> str:
    params_with_ms = dict(params)
    params_with_ms["msToken"] = ""
    ab = ABogus()
    a_bogus_raw = ab.get_value(params_with_ms, method)
    a_bogus = quote(a_bogus_raw, safe="")
    return f"{base_url}?{urlencode(params_with_ms)}&a_bogus={a_bogus}"


def _get_ttwid(session) -> str:
    payload = (
        '{"region":"cn","aid":1128,"needFid":false,"service":"www.douyin.com",'
        '"migrate_info":{"ticket":"","source":"node"},'
        '"cbUrlProtocol":"https","union":true}'
    )
    try:
        resp = session.post(
            API_TTWID,
            data=payload,
            headers={**HEADERS, "Content-Type": "application/json"},
            timeout=10,
        )
        return resp.cookies.get("ttwid", "")
    except Exception:
        return ""


def _build_session(cookie_str: str) -> requests.Session:
    session = requests.Session(impersonate="chrome124")
    session.headers.update(HEADERS)

    ttwid = _get_ttwid(session)
    if ttwid:
        session.cookies.set("ttwid", ttwid, domain=".douyin.com")

    verify_fp = _gen_verify_fp()
    s_v_web_id = _gen_verify_fp()
    session.cookies.set("verifyFp", verify_fp, domain=".douyin.com")
    session.cookies.set("s_v_web_id", s_v_web_id, domain=".douyin.com")

    ms_token = _gen_random_str(126) + "=="
    session.cookies.set("msToken", ms_token, domain=".douyin.com")

    for item in cookie_str.split(";"):
        item = item.strip()
        if "=" in item:
            k, v = item.split("=", 1)
            session.cookies.set(k.strip(), v.strip())

    return session


def _check_login(session: requests.Session) -> bool:
    params = {"device_platform": "webapp", "aid": "6383"}
    endpoint = _sign_url(API_SELF, params)
    try:
        r = session.get(endpoint, timeout=8)
        return r.json().get("status_code") == 0
    except Exception:
        return False


def _fetch_sticker_list(session: requests.Session) -> list:
    cursor = 0
    has_more = True
    stickers = []

    while has_more:
        if _check_cancel():
            return stickers

        params = {
            "device_platform": "webapp",
            "aid": "1128",
            "channel": "channel_pc_web",
            "scenes": "CUSTOM_STICKER_PAGE",
            "custom_cursor": str(cursor),
            "custom_page_size": "100",
            "version_code": "170400",
            "version_name": "17.4.0",
            "cookie_enabled": "true",
            "screen_width": "1536",
            "screen_height": "864",
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Chrome",
            "browser_version": "90.0.4430.212",
            "browser_online": "true",
            "engine_name": "Blink",
            "engine_version": "90.0.4430.212",
            "os_name": "Windows",
            "os_version": "10",
            "cpu_core_num": "12",
            "device_memory": "8",
            "platform": "PC",
        }

        try:
            endpoint = _sign_url(API_STICKER, params)
            resp = session.get(endpoint, timeout=15)

            if resp.status_code == 403:
                return None

            if resp.status_code != 200:
                break

            data = resp.json()
            page = data.get("custom_sticker_page_list", {})

            for res in page.get("resources", []):
                for s in res.get("stickers", []):
                    url_info = s.get("animate_url") or s.get("static_url")
                    if url_info and url_info.get("url_list"):
                        best_url = url_info["url_list"][0]
                        for u in url_info["url_list"]:
                            if "origin" in u.lower():
                                best_url = u
                                break
                        stickers.append(
                            {
                                "id": s.get("id_str", "unknown"),
                                "url": best_url,
                            }
                        )

            has_more = page.get("has_more", False)
            next_cursor = page.get("next_cursor", cursor)
            if not has_more or next_cursor == 0 or next_cursor == cursor:
                break
            cursor = next_cursor

        except Exception as e:
            logger.warning("fetch list error: %s", e)
            break

    return stickers


def _download_sticker(url: str, tmp_dir: str, session, sticker_id: str = "") -> str:
    """下载单个表情包到临时目录，复用已配置的 session 保持 cookies/TLS 状态"""
    ext = "webp"
    if ".gif" in url.lower():
        ext = "gif"
    elif ".png" in url.lower():
        ext = "png"

    resp = session.get(url, timeout=12)
    resp.raise_for_status()

    data = resp.content
    fhash = hashlib.sha256(data).hexdigest()
    fname = f"{fhash[:16]}.{ext}"
    fpath = os.path.join(tmp_dir, fname)
    with open(fpath, "wb") as f:
        f.write(data)
    return fpath


def start_douyin_import(import_callback, cookie: str, job_manager=None) -> bool:
    """启动抖音表情包下载导入（全部下载），后台线程执行"""
    global _DOUYIN_CANCEL

    if job_manager is not None and job_manager.active("import.douyin") is not None:
        return False
    with _DOUYIN_LOCK:
        if _DOUYIN_STATE["status"] == "running":
            return False
        _DOUYIN_CANCEL = False
        _DOUYIN_STATE.update(
            status="running",
            progress=0,
            message="正在连接...",
            error="",
            error_code="",
            total=0,
            done=0,
            imported=0,
            rejected=0,
        )

    def _run():
        global _DOUYIN_CANCEL
        tmp_dir = tempfile.mkdtemp(prefix="dy_")
        downloaded = []
        download_failed = 0

        try:
            _update_dy(message="初始化 Session...")
            session = _build_session(cookie)
            if _check_cancel():
                _update_dy(status="cancelled", message="已取消")
                return

            _update_dy(message="检查登录状态...")
            if not _check_login(session):
                logger.error("douyin import: 登录失败（Cookie 无效或已过期）")
                _update_dy(
                    status="error",
                    error="登录失败：Cookie 无效或已过期",
                    error_code="login_failed",
                )
                return

            _update_dy(message="获取表情列表...")
            stickers = _fetch_sticker_list(session)

            if _check_cancel():
                _update_dy(status="cancelled", message="已取消")
                return

            if stickers is None:
                logger.error("douyin import: 接口返回 403，签名验证失败")
                _update_dy(
                    status="error",
                    error="接口返回 403：签名验证失败",
                    error_code="sign_failed",
                )
                return

            if not stickers:
                logger.error("douyin import: 未获取到任何表情包")
                _update_dy(
                    status="error",
                    error="未获取到任何表情包",
                    error_code="no_stickers",
                )
                return

            total = len(stickers)
            _update_dy(total=total, message=f"找到 {total} 个表情，开始下载...")

            for i, item in enumerate(stickers):
                if _check_cancel():
                    _update_dy(status="cancelled", message="已取消")
                    return

                try:
                    fpath = _download_sticker(item["url"], tmp_dir, session, item["id"])
                    downloaded.append(fpath)
                    done = i + 1
                    _update_dy(
                        done=done,
                        progress=int(done * 100 / total),
                        message=f"下载中 {done}/{total}",
                    )
                except Exception as e:
                    logger.warning("download %s failed: %s", item["id"], e)
                    download_failed += 1
                    done = i + 1
                    _update_dy(
                        done=done,
                        progress=int(done * 100 / total),
                        message=f"下载中 {done}/{total}",
                        download_failed=download_failed,
                    )

            if _check_cancel():
                _update_dy(status="cancelled", message="已取消")
                return

            _update_dy(message="导入数据库...")

            if downloaded and import_callback:
                result = import_callback(downloaded)
                imported = len(result.get("ids", []))
                rejected = result.get("rejected", 0)
                msg = f"导入完成：{imported} 个成功"
                if rejected:
                    msg += f"，{rejected} 个跳过"
                if download_failed:
                    msg += f"，{download_failed} 个下载失败"
                _update_dy(
                    status="done",
                    progress=100,
                    message=msg,
                    imported=imported,
                    rejected=rejected,
                    download_failed=download_failed,
                )
            else:
                msg = "下载完成（无有效数据）"
                if download_failed:
                    msg += f"，{download_failed} 个下载失败"
                _update_dy(
                    status="done",
                    progress=100,
                    message=msg,
                    download_failed=download_failed,
                )

        except Exception as e:
            logger.error("douyin import error: %s", e)
            _update_dy(status="error", error=str(e), error_code="exception")
        finally:
            import shutil

            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    if job_manager is None:
        threading.Thread(target=_run, daemon=True).start()
    else:

        def target(context):
            global _DOUYIN_JOB_CANCEL, _DOUYIN_JOB_SNAPSHOT
            try:
                _run()
                if _DOUYIN_STATE["status"] == "error":
                    raise RuntimeError(
                        f"{_DOUYIN_STATE['error_code']}: {_DOUYIN_STATE['error']}"
                    )
            finally:
                _DOUYIN_JOB_CANCEL = None
                _DOUYIN_JOB_SNAPSHOT = None

        try:
            _, created = job_manager.try_start(
                "import.douyin",
                target,
                resources=("douyin",),
                on_admit=lambda record, context: _bind_douyin_job(
                    job_manager, record, context
                ),
            )
        except BaseException:
            with _DOUYIN_LOCK:
                _DOUYIN_JOB_CANCEL = None
                _DOUYIN_JOB_SNAPSHOT = None
                _DOUYIN_CANCEL = False
                _DOUYIN_STATE["status"] = "idle"
            raise
        if not created:
            return False
    return True
