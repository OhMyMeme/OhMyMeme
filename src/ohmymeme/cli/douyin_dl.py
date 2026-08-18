"""
抖音表情包下载器 — 命令行测试入口
下载前 N 个表情包到指定目录，不转换格式

用法:
  python -m ohmymeme.cli.douyin_dl
  python -m ohmymeme.cli.douyin_dl --limit 5
  python -m ohmymeme.cli.douyin_dl --out /tmp/emojis
  python -m ohmymeme.cli.douyin_dl --cookie "..."
"""

import argparse
import os
import random
import string
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlencode

from curl_cffi import requests

from ohmymeme.integrations.imports.abogus import ABogus

# ─── 配置 ───

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


def gen_random_str(length: int = 126) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=length))


def gen_verify_fp() -> str:
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


def sign_url(base_url: str, params: dict, method: str = "GET") -> str:
    params_with_ms = dict(params)
    params_with_ms["msToken"] = ""
    ab = ABogus()
    a_bogus_raw = ab.get_value(params_with_ms, method)
    a_bogus = quote(a_bogus_raw, safe="")
    return f"{base_url}?{urlencode(params_with_ms)}&a_bogus={a_bogus}"


def build_session(cookie_str: str = "") -> requests.Session:
    session = requests.Session(impersonate="chrome124")
    session.headers.update(HEADERS)

    ttwid = get_ttwid(session)
    if ttwid:
        session.cookies.set("ttwid", ttwid, domain=".douyin.com")

    verify_fp = gen_verify_fp()
    s_v_web_id = gen_verify_fp()
    session.cookies.set("verifyFp", verify_fp, domain=".douyin.com")
    session.cookies.set("s_v_web_id", s_v_web_id, domain=".douyin.com")

    ms_token = gen_random_str(126) + "=="
    session.cookies.set("msToken", ms_token, domain=".douyin.com")

    if cookie_str:
        for item in cookie_str.split(";"):
            item = item.strip()
            if "=" in item:
                k, v = item.split("=", 1)
                session.cookies.set(k.strip(), v.strip())

    return session


def get_ttwid(session: requests.Session) -> str:
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
        ttwid = resp.cookies.get("ttwid", "")
        if ttwid:
            print(f"  ttwid OK: {ttwid[:20]}...")
            return ttwid
    except Exception as e:
        print(f"  ttwid 失败（继续）: {e}")
    return ""


def check_login(session: requests.Session) -> bool:
    params = {"device_platform": "webapp", "aid": "6383"}
    endpoint = sign_url(API_SELF, params)
    try:
        r = session.get(endpoint, timeout=8)
        data = r.json()
        return data.get("status_code") == 0
    except Exception:
        return False


def fetch_sticker_list(session: requests.Session, limit: int = 10) -> list:
    print("\n拉取表情列表...")
    cursor = 0
    has_more = True
    stickers = []

    while has_more and len(stickers) < limit:
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
            endpoint = sign_url(API_STICKER, params)
            resp = session.get(endpoint, timeout=15)

            if resp.status_code == 403:
                print("  403: 签名验证失败或需要登录 Cookie")
                return []

            if resp.status_code != 200:
                print(f"  HTTP {resp.status_code}")
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
                        if len(stickers) >= limit:
                            break

            has_more = page.get("has_more", False)
            cursor = page.get("next_cursor", cursor)

            if not has_more or cursor == 0:
                break

            print(f"  已发现 {len(stickers)} 个...", flush=True)

        except Exception as e:
            print(f"  请求异常: {e}")
            break

    print(f"  共找到 {len(stickers)} 个表情（限制 {limit}）")
    return stickers[:limit]


def download_stickers(stickers: list, out_dir: Path) -> tuple:
    out_dir.mkdir(parents=True, exist_ok=True)
    ok = 0
    fail = 0

    print(f"\n下载到: {out_dir}")

    for i, item in enumerate(stickers, 1):
        url = item["url"]
        ext = "webp"
        if ".gif" in url.lower():
            ext = "gif"
        elif ".png" in url.lower():
            ext = "png"

        fname = f"sticker_{item['id']}.{ext}"
        fpath = out_dir / fname

        try:
            resp = requests.get(url, timeout=12, impersonate="chrome124")
            resp.raise_for_status()
            fpath.write_bytes(resp.content)
            ok += 1
            size_kb = len(resp.content) / 1024
            print(f"  [{i}/{len(stickers)}] {fname} ({size_kb:.1f} KB)")
        except Exception as e:
            fail += 1
            print(f"  [{i}/{len(stickers)}] {fname} FAILED: {e}")

    return ok, fail


def main():
    parser = argparse.ArgumentParser(description="抖音表情包下载（测试用）")
    parser.add_argument("--limit", type=int, default=10, help="下载数量上限")
    default_out = str(Path.home() / "Downloads" / "testD")
    parser.add_argument("--out", type=str, default=default_out, help="输出目录")
    parser.add_argument("--cookie", type=str, default="", help="抖音 Cookie")
    args = parser.parse_args()

    print("=" * 50)
    print("  抖音表情包下载器 (测试)")
    print("=" * 50)

    cookie = args.cookie or os.getenv("DY_COOKIE", "")
    if not cookie and Path("cookie.txt").exists():
        cookie = Path("cookie.txt").read_text().strip()
        print("从 cookie.txt 读取 Cookie")

    if not cookie:
        print("\n未提供 Cookie，请先登录抖音网页版")
        print("  方式 1: --cookie 'sessionid=xxx; ...'")
        print("  方式 2: export DY_COOKIE='sessionid=xxx; ...'")
        print("  方式 3: 在当前目录创建 cookie.txt 并粘贴 Cookie")
        sys.exit(1)

    session = build_session(cookie)

    print("\n检查登录状态...")
    if not check_login(session):
        print("  登录检查失败：Cookie 可能已过期")
        response = input("  是否继续？(y/N) ").strip().lower()
        if response != "y":
            sys.exit(1)
    else:
        print("  登录有效")

    stickers = fetch_sticker_list(session, limit=args.limit)
    if not stickers:
        print("\n未获取到任何表情包")
        sys.exit(1)

    out_dir = Path(args.out)
    ok, fail = download_stickers(stickers, out_dir)

    print(f"\n完成: 成功 {ok}, 失败 {fail}")
    print(f"输出: {out_dir}")


if __name__ == "__main__":
    main()
