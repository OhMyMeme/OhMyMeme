"""上传路由的有界请求体读取。"""

UPLOAD_BODY_LIMIT = 28 * 1024 * 1024


def read_upload_body(stream):
    """读取不超过本地上传限制的请求体。"""
    body = stream.read(UPLOAD_BODY_LIMIT + 1)
    if len(body) > UPLOAD_BODY_LIMIT:
        return None
    return body
