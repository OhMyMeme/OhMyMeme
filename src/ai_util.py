# -*- coding: utf-8 -*-
"""AI 工具模块

提供 AI 编辑功能所需的 HTTP 调用与图片处理函数：
- chat_completion: OpenAI 兼容的多模态对话（整理表情包用）
- image_generation: 文生图（生成表情包用）
- download_image: 从 URL 下载图片到本地
- encode_image_base64: 本地图片转 base64 data URI
- ai_organize_memes: 遍历表情包调 AI 返回标签和分组建议
- ai_search_images: 按关键词搜索图片返回直链列表

全部使用标准库，不引入外部依赖。配置由调用方传入（base_url/api_key/model），
兼容任意 OpenAI 格式的服务商。
"""

import base64
import json
import os
import re
import urllib.parse
import urllib.request

# HTTP 请求超时（秒）
_HTTP_TIMEOUT = 60
# 图片下载超时（秒）
_DOWNLOAD_TIMEOUT = 30
# 单次 AI 请求最大 token
_MAX_TOKENS = 1024


def _post_json(url, api_key, payload, timeout=_HTTP_TIMEOUT):
    # 发送 JSON POST 请求并返回解析后的 JSON
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("Authorization", "Bearer %s" % api_key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        raise ValueError("请求失败: %s" % e)
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise ValueError("响应不是有效 JSON: %s" % body[:200])


def _normalize_base_url(base_url):
    # 去除末尾斜杠，确保可拼接路径
    return base_url.rstrip("/")


def chat_completion(base_url, api_key, model, messages, max_tokens=_MAX_TOKENS):
    # 调用 OpenAI 兼容的 /v1/chat/completions，返回 content 文本
    if not model:
        raise ValueError("整理模型不能为空")
    url = _normalize_base_url(base_url) + "/v1/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    data = _post_json(url, api_key, payload)
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise ValueError("AI 响应结构异常: %s" % json.dumps(data)[:200])


def _image_result(data, action):
    # 解析 OpenAI 图片接口响应
    try:
        item = data["data"][0]
    except (KeyError, IndexError, TypeError):
        raise ValueError("%s响应异常: %s" % (action, json.dumps(data)[:200]))
    if "b64_json" in item and item["b64_json"]:
        return {"b64": item["b64_json"]}
    if "url" in item and item["url"]:
        return {"url": item["url"]}
    raise ValueError("%s响应缺少图片数据" % action)


def image_generation(base_url, api_key, model, prompt, size="1024x1024", n=1):
    # 调用 OpenAI 兼容的 /v1/images/generations，返回首张图片 URL 或 base64
    if not model:
        raise ValueError("生图模型不能为空")
    url = _normalize_base_url(base_url) + "/v1/images/generations"
    payload = {
        "model": model,
        "prompt": prompt,
        "n": 1,
    }
    if size:
        payload["size"] = size
    return _image_result(_post_json(url, api_key, payload), "文生图")


def image_edit(base_url, api_key, model, image_path, prompt, size="1024x1024"):
    # 调用 OpenAI 兼容的 /v1/images/edits，不覆盖源图片
    if not model:
        raise ValueError("生图模型不能为空")
    if not image_path or not os.path.isfile(image_path):
        raise ValueError("原始图片不存在")
    boundary = "----OhMyMeme%s" % base64.urlsafe_b64encode(os.urandom(12)).decode(
        "ascii"
    )
    parts = []

    def add_field(name, value):
        parts.append(("--%s\r\n" % boundary).encode("ascii"))
        parts.append(
            ('Content-Disposition: form-data; name="%s"\r\n\r\n' % name).encode("utf-8")
        )
        parts.append(str(value).encode("utf-8"))
        parts.append(b"\r\n")

    add_field("model", model)
    add_field("prompt", prompt)
    add_field("n", 1)
    if size:
        add_field("size", size)
    filename = os.path.basename(image_path)
    ext = os.path.splitext(filename)[1].lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(ext, "application/octet-stream")
    with open(image_path, "rb") as f:
        raw = f.read()
    parts.append(("--%s\r\n" % boundary).encode("ascii"))
    parts.append(
        (
            'Content-Disposition: form-data; name="image"; filename="%s"\r\n' % filename
        ).encode("utf-8")
    )
    parts.append(("Content-Type: %s\r\n\r\n" % mime).encode("ascii"))
    parts.append(raw)
    parts.append(b"\r\n")
    parts.append(("--%s--\r\n" % boundary).encode("ascii"))
    req = urllib.request.Request(
        _normalize_base_url(base_url) + "/v1/images/edits",
        data=b"".join(parts),
        method="POST",
    )
    req.add_header("Content-Type", "multipart/form-data; boundary=%s" % boundary)
    if api_key:
        req.add_header("Authorization", "Bearer %s" % api_key)
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:
        raise ValueError("图片编辑请求失败: %s" % e)
    return _image_result(data, "图片编辑")


def download_image(url, dest_path, timeout=_DOWNLOAD_TIMEOUT):
    # 从 URL 下载图片到 dest_path，校验 Content-Type 为图片
    req = urllib.request.Request(url, method="GET")
    req.add_header(
        "User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if "image" not in ctype and not _guess_image_from_url(url):
                return False
            data = resp.read()
    except Exception:
        return False
    if not data:
        return False
    try:
        with open(dest_path, "wb") as f:
            f.write(data)
    except Exception:
        return False
    return True


def _guess_image_from_url(url):
    # 从 URL 后缀猜测是否为图片
    low = url.lower().split("?")[0]
    return low.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"))


def encode_image_base64(path):
    # 读取本地图片转 base64 data URI（供多模态消息构造）
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext == "jpg":
        ext = "jpeg"
    if ext not in ("png", "jpeg", "gif", "webp", "bmp"):
        ext = "png"
    try:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
    except Exception:
        return ""
    return "data:image/%s;base64,%s" % (ext, b64)


def _parse_ai_json(text):
    # 宽松解析 AI 返回的 JSON（可能带 markdown 代码块或多余文字）
    if not text:
        return None
    text = text.strip()
    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 尝试提取代码块中的 JSON
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 尝试提取第一个 {...} 片段
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


def ai_organize_memes(
    base_url,
    api_key,
    model,
    meme_list,
    on_progress=None,
    should_stop=None,
    style="general",
):
    # 遍历表情包调多模态 AI 返回每张的标签和分组建议
    # meme_list: [{"id":int, "path":"", "filename":""}, ...]
    # 返回标签、分组、描述和图片文字建议的列表
    results = []
    total = len(meme_list)
    style_names = {
        "general": "通用聊天",
        "anime": "二次元",
        "work": "职场",
        "gaming": "游戏群",
    }
    style_text = style_names.get(style, style_names["general"])
    for i, item in enumerate(meme_list):
        if should_stop and should_stop():
            break
        data_uri = encode_image_base64(item["path"])
        if not data_uri:
            if on_progress:
                on_progress(i, total, "跳过（无法读取）")
            continue
        messages = [
            {
                "role": "system",
                "content": "你是表情包分类助手。分析图片内容，返回 JSON，格式为 "
                '{"tags":["标签1","标签2"],"collection":"分组名","description":"图片描述","ocr_text":"图片文字"}。'
                "标签用简短中文，2-4 个；分组名用简短中文。"
                "description 和 ocr_text 可为空。整理风格为%s，"
                "按该场景选择标签和分组。只返回 JSON，不要其他文字。" % style_text,
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "分析这张表情包，返回标签和分组建议的 JSON。",
                    },
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            },
        ]
        try:
            content = chat_completion(base_url, api_key, model, messages)
            parsed = _parse_ai_json(content)
            if parsed and isinstance(parsed, dict):
                tags = parsed.get("tags", [])
                if not isinstance(tags, list):
                    tags = []
                collection = parsed.get("collection", "")
                if not isinstance(collection, str):
                    collection = ""
                description = parsed.get("description", "")
                ocr_text = parsed.get("ocr_text", "")
                results.append(
                    {
                        "id": item["id"],
                        "tags": tags,
                        "collection": collection,
                        "description": (
                            description if isinstance(description, str) else ""
                        ),
                        "ocr_text": ocr_text if isinstance(ocr_text, str) else "",
                    }
                )
            else:
                if on_progress:
                    on_progress(i, total, "AI 返回无法解析，跳过")
        except Exception:
            if on_progress:
                on_progress(i, total, "AI 请求失败，跳过")
        if on_progress:
            on_progress(i + 1, total, "处理 %d/%d" % (i + 1, total))
    return results


def ai_search_images(
    keyword, count=10, source="bing", on_progress=None, should_stop=None
):
    # 按关键词搜索图片，返回直链列表
    # 初始实现 Bing 图片搜索 HTML 抓取，留 source 分支扩展
    if source == "bing":
        return _search_bing_images(keyword, count, on_progress, should_stop)
    # 预留：其他来源可在此分支扩展
    return []


def _search_bing_images(keyword, count, on_progress=None, should_stop=None):
    # 从 Bing 图片搜索抓取图片直链
    url = "https://www.bing.com/images/search?q=%s&form=HDRSC2" % urllib.parse.quote(
        keyword
    )
    req = urllib.request.Request(url, method="GET")
    req.add_header(
        "User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    )
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return []
    # Bing 图片结果中 murl 字段为原图直链
    urls = re.findall(r'"murl":"(https?://[^"]+)"', html)
    seen = set()
    result = []
    for u in urls:
        if should_stop and should_stop():
            break
        if u in seen:
            continue
        seen.add(u)
        result.append(u)
        if len(result) >= count:
            break
    if on_progress:
        on_progress(len(result), count, "找到 %d 张" % len(result))
    return result
