# -*- coding: utf-8 -*-
"""
GIF 增量隐写工具：只把"原图比 GIF 多出来的信息"藏入 GIF，可无损还原。

原理：
    1. GIF 文件以 0x3B（Trailer）结尾，解码器读到该字节即停止解析，
       之后的数据会被忽略 —— 隐写数据就追加在这里，GIF 可正常查看。
    2. GIF 与原图分辨率相同，其像素是原图的调色板量化（有损）版本。
       只需藏 残差 = (原图像素 - GIF像素) mod 256，解码时用
       GIF 渲染像素 + 残差 (mod 256) 逐字节精确还原。
    3. 原图支持 PNG / JPEG / WebP / BMP / TIFF 等一切 Pillow 可解码
       为 RGB / RGBA / L（灰度）的静态图：
         - RGB            -> RGB 残差
         - RGBA/LA/透明P  -> 混合模式：RGB 残差 + Alpha 平面
         - L（灰度）       -> 灰度残差
       残差用 WebP 无损（空间预测器强）或 LZMA 压缩。
    4. 若增量不适用（尺寸不一致、动图等）或反而更大，自动回退整图嵌入
       （原图文件字节原样保存）—— 所有可行候选全部计算，取体积最小者。
    5. 还原目标：图像像素与原图逐字节一致，默认输出无损 PNG。
       注意：JPEG 等有损格式的"原图"指其解码后的像素；若需原文件
       字节级还原（含元数据），整图模式被选中时可做到。

CLI 用法：
    编码：python gif_stego.py encode 转换后的.gif 原图.jpg 输出.gif
    解码：python gif_stego.py decode 输出.gif 还原图.png

库用法（由应用调用）：
    from .gif_stego import make_stego_gif, decode
    make_stego_gif("原图.png", "隐写.gif", quiet=True)
    decode("隐写.gif", "还原.png", quiet=True)
"""

import argparse
import io
import lzma
import os
import struct
import sys
import tempfile

from PIL import Image

MAGIC = b"STG3"  # 隐写数据标识（v3：多格式支持，无元数据）
GIF_TRAILER = 0x3B  # GIF 文件结束字节

MODE_FULL = 0  # 整图嵌入（LZMA 压缩原图文件字节，任意格式）
MODE_DELTA_LZMA = 1  # RGB 残差，LZMA
MODE_DELTA_WEBP = 2  # RGB 残差，WebP 无损
MODE_RGBA_LZMA = 3  # 混合：RGB 残差 + Alpha 平面，LZMA
MODE_RGBA_WEBP = 4  # 混合：RGB 残差 + Alpha 平面，WebP 无损
MODE_L_LZMA = 5  # 灰度残差，LZMA
MODE_L_WEBP = 6  # 灰度残差，WebP 无损

MODE_NAMES = {
    MODE_FULL: "整图模式",
    MODE_DELTA_LZMA: "增量-LZMA",
    MODE_DELTA_WEBP: "增量-WebP",
    MODE_RGBA_LZMA: "混合-LZMA（RGB残差+Alpha）",
    MODE_RGBA_WEBP: "混合-WebP（RGB残差+Alpha）",
    MODE_L_LZMA: "灰度增量-LZMA",
    MODE_L_WEBP: "灰度增量-WebP",
}


def _render_gif(gif_bytes: bytes, mode: str) -> Image.Image:
    """把 GIF（首帧）渲染为指定模式的像素。编码/解码用同一函数，保证一致。"""
    im = Image.open(io.BytesIO(gif_bytes))
    if getattr(im, "n_frames", 1) != 1:
        raise ValueError("暂不支持多帧（动画）GIF")
    return im.convert(mode)


def _has_alpha(im: Image.Image) -> bool:
    return im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)


def _delta_data(orig_path: str, gif_bytes: bytes):
    """计算残差数据。返回 (kind, w, h, 残差, alpha|None)；不适用返回 None。
    kind ∈ "RGB" | "RGBA" | "L"。"""
    orig_im = Image.open(orig_path)
    if getattr(orig_im, "n_frames", 1) != 1:  # 动图不做增量
        return None
    if orig_im.mode == "RGB":
        kind = "RGB"
    elif _has_alpha(orig_im):
        orig_im = orig_im.convert("RGBA")
        kind = "RGBA"
    elif orig_im.mode == "L":
        kind = "L"
    elif orig_im.mode == "P":  # 无透明调色板图按 RGB 处理
        orig_im = orig_im.convert("RGB")
        kind = "RGB"
    else:
        return None

    w, h = orig_im.size
    if kind == "L":
        g = _render_gif(gif_bytes, "L").tobytes()
        if Image.open(io.BytesIO(gif_bytes)).size != (w, h):
            return None
        o = orig_im.tobytes()
        return kind, w, h, bytes(((o[i] - g[i]) & 0xFF) for i in range(len(o))), None

    gif_rgb = _render_gif(gif_bytes, "RGB")
    if orig_im.size != gif_rgb.size:  # 尺寸不一致无法做像素差
        return None
    g = gif_rgb.tobytes()

    if kind == "RGB":
        o = orig_im.tobytes()
        return kind, w, h, bytes(((o[i] - g[i]) & 0xFF) for i in range(len(o))), None

    o = orig_im.tobytes()  # RGBA 交错
    delta_rgb = bytearray(w * h * 3)
    alpha = bytearray(w * h)
    j = k = 0
    for i in range(0, len(o), 4):
        delta_rgb[j] = (o[i] - g[j]) & 0xFF
        delta_rgb[j + 1] = (o[i + 1] - g[j + 1]) & 0xFF
        delta_rgb[j + 2] = (o[i + 2] - g[j + 2]) & 0xFF
        alpha[k] = o[i + 3]
        j += 3
        k += 1
    return kind, w, h, bytes(delta_rgb), bytes(alpha)


def _webp_save(img: Image.Image) -> bytes:
    # exact=True：强制保留全透明像素下的 RGB 值（libwebp 默认会修改它们以利压缩）
    buf = io.BytesIO()
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")  # 灰度转 RGB 存储；灰度值 L->RGB->L 为恒等映射，无损
    img.save(buf, format="WEBP", lossless=True, quality=100, method=6, exact=True)
    return buf.getvalue()


def _candidates(gif_bytes: bytes, orig_path: str, orig_bytes: bytes):
    """生成所有可行的 (模式, 载荷) 候选。"""
    cands = []

    # 候选 1：整图嵌入（任意文件类型）
    ext = orig_path.rsplit(".", 1)[-1].encode("utf-8") if "." in orig_path else b"bin"
    raw = struct.pack("B", len(ext)) + ext + orig_bytes
    cands.append(
        (MODE_FULL, struct.pack(">I", len(raw)) + lzma.compress(raw, preset=9))
    )

    # 其余候选：增量 / 混合
    dd = _delta_data(orig_path, gif_bytes)
    if dd is None:
        return cands
    kind, w, h, delta, alpha = dd
    head = struct.pack(">II", w, h)

    if kind == "RGB":
        raw = head + delta
        cands.append(
            (
                MODE_DELTA_LZMA,
                struct.pack(">I", len(raw)) + lzma.compress(raw, preset=9),
            )
        )
        try:
            # +128 偏移使小误差聚集在 128 附近；mod 256 双射可精确还原
            shifted = bytes((b + 128) & 0xFF for b in delta)
            cands.append(
                (
                    MODE_DELTA_WEBP,
                    head + _webp_save(Image.frombytes("RGB", (w, h), shifted)),
                )
            )
        except Exception:
            pass
    elif kind == "L":
        raw = head + delta
        cands.append(
            (MODE_L_LZMA, struct.pack(">I", len(raw)) + lzma.compress(raw, preset=9))
        )
        try:
            shifted = bytes((b + 128) & 0xFF for b in delta)
            cands.append(
                (MODE_L_WEBP, head + _webp_save(Image.frombytes("L", (w, h), shifted)))
            )
        except Exception:
            pass
    else:
        raw = head + delta + alpha
        cands.append(
            (MODE_RGBA_LZMA, struct.pack(">I", len(raw)) + lzma.compress(raw, preset=9))
        )
        try:
            # RGB 残差 +128 偏移，Alpha 原样，合并为一张 RGBA WebP
            n = w * h
            shifted = bytearray(n * 4)
            for i in range(n):
                shifted[i * 4] = (delta[i * 3] + 128) & 0xFF
                shifted[i * 4 + 1] = (delta[i * 3 + 1] + 128) & 0xFF
                shifted[i * 4 + 2] = (delta[i * 3 + 2] + 128) & 0xFF
                shifted[i * 4 + 3] = alpha[i]
            cands.append(
                (
                    MODE_RGBA_WEBP,
                    head + _webp_save(Image.frombytes("RGBA", (w, h), bytes(shifted))),
                )
            )
        except Exception:
            pass

    return cands


def encode(gif_path: str, orig_path: str, out_path: str, quiet: bool = False) -> None:
    """把原图"多出的信息"写入 GIF，生成新的 GIF。"""
    with open(gif_path, "rb") as f:
        gif_data = f.read()
    with open(orig_path, "rb") as f:
        orig_bytes = f.read()

    if not gif_data or gif_data[-1] != GIF_TRAILER:
        raise ValueError("输入的 GIF 文件格式异常（未以 0x3B Trailer 结尾）")
    if MAGIC in gif_data:
        raise ValueError("该 GIF 已包含隐写数据，请使用原始 GIF")

    mode, payload = min(
        _candidates(gif_data, orig_path, orig_bytes), key=lambda c: len(c[1])
    )

    with open(out_path, "wb") as f:
        f.write(gif_data + MAGIC + struct.pack("B", mode) + payload)

    if not quiet:
        hidden = len(MAGIC) + 1 + len(payload)
        print(f"编码完成（{MODE_NAMES[mode]}）：{out_path}")
        print(f"  GIF 大小     : {len(gif_data):,} 字节")
        print(f"  原图大小     : {len(orig_bytes):,} 字节")
        print(
            f"  隐写数据     : {hidden:,} 字节（占原图 {hidden / len(orig_bytes):.0%}）"
        )
        print(f"  输出总大小   : {len(gif_data) + hidden:,} 字节")


def _restore(
    w: int,
    h: int,
    delta: bytes,
    alpha,
    gif_data: bytes,
    out_path: str,
    mode_name: str,
    quiet: bool = False,
) -> None:
    """GIF 像素 + 残差 (mod 256) 还原图像并保存。"""
    if alpha is None and len(delta) == w * h:  # 灰度
        g = _render_gif(gif_data, "L").tobytes()
        if len(g) != len(delta):
            raise ValueError("GIF 尺寸与残差不匹配，文件可能被改动")
        orig = bytes(((g[i] + delta[i]) & 0xFF) for i in range(len(g)))
        im = Image.frombytes("L", (w, h), orig)
    else:
        g = _render_gif(gif_data, "RGB").tobytes()
        if len(g) != w * h * 3 or len(delta) != w * h * 3:
            raise ValueError("GIF 尺寸与残差不匹配，文件可能被改动")
        if alpha is None:  # RGB
            orig = bytes(((g[i] + delta[i]) & 0xFF) for i in range(len(g)))
            im = Image.frombytes("RGB", (w, h), orig)
        else:  # RGBA
            if len(alpha) != w * h:
                raise ValueError("隐写数据损坏（Alpha 长度不匹配）")
            orig = bytearray(w * h * 4)
            j = 0
            for i in range(0, len(orig), 4):
                orig[i] = (g[j] + delta[j]) & 0xFF
                orig[i + 1] = (g[j + 1] + delta[j + 1]) & 0xFF
                orig[i + 2] = (g[j + 2] + delta[j + 2]) & 0xFF
                orig[i + 3] = alpha[i // 4]
                j += 3
            im = Image.frombytes("RGBA", (w, h), bytes(orig))

    if "." not in out_path.rsplit("/", 1)[-1]:
        out_path += ".png"
    im.save(out_path)  # 存为无损 PNG，避免二次有损编码
    if not quiet:
        print(f"解码完成（{mode_name}）：{out_path}（{w}x{h}，像素与原图完全一致）")


def decode(steg_path: str, out_path: str, quiet: bool = False) -> None:
    """从隐写 GIF 中还原原图。"""
    with open(steg_path, "rb") as f:
        data = f.read()

    pos = data.rfind(MAGIC)  # 从尾部找标识，避免 GIF 内部巧合匹配
    if pos == -1:
        raise ValueError("未在该 GIF 中找到隐写数据（或它是旧版本格式）")

    gif_data, blob = data[:pos], data[pos + len(MAGIC) :]
    mode = blob[0]

    if mode == MODE_FULL:
        (raw_len,) = struct.unpack(">I", blob[1:5])
        raw = lzma.decompress(blob[5:])
        if len(raw) != raw_len:
            raise ValueError("隐写数据损坏（长度校验失败）")
        ext_len = raw[0]
        ext = raw[1 : 1 + ext_len].decode("utf-8")
        orig_bytes = raw[1 + ext_len :]
        if "." not in out_path.rsplit("/", 1)[-1]:
            out_path = f"{out_path}.{ext}"
        with open(out_path, "wb") as f:
            f.write(orig_bytes)
        if not quiet:
            print(f"解码完成（整图模式）：{out_path}（还原 {len(orig_bytes):,} 字节）")

    elif mode in (MODE_DELTA_LZMA, MODE_RGBA_LZMA, MODE_L_LZMA):
        (raw_len,) = struct.unpack(">I", blob[1:5])
        raw = lzma.decompress(blob[5:])
        if len(raw) != raw_len:
            raise ValueError("隐写数据损坏（长度校验失败）")
        w, h = struct.unpack(">II", raw[:8])
        body = raw[8:]
        if mode == MODE_RGBA_LZMA:
            n = w * h * 3
            _restore(
                w,
                h,
                body[:n],
                body[n:],
                gif_data,
                out_path,
                MODE_NAMES[mode],
                quiet=quiet,
            )
        else:
            _restore(
                w, h, body, None, gif_data, out_path, MODE_NAMES[mode], quiet=quiet
            )

    elif mode in (MODE_DELTA_WEBP, MODE_RGBA_WEBP, MODE_L_WEBP):
        w, h = struct.unpack(">II", blob[1:9])
        stored = Image.open(io.BytesIO(blob[9:]))
        if mode == MODE_DELTA_WEBP:
            s = stored.convert("RGB").tobytes()
            delta = bytes((b - 128) & 0xFF for b in s)
            _restore(
                w, h, delta, None, gif_data, out_path, MODE_NAMES[mode], quiet=quiet
            )
        elif mode == MODE_L_WEBP:
            s = stored.convert("L").tobytes()
            delta = bytes((b - 128) & 0xFF for b in s)
            _restore(
                w, h, delta, None, gif_data, out_path, MODE_NAMES[mode], quiet=quiet
            )
        else:
            s = stored.convert("RGBA").tobytes()
            delta = bytearray(w * h * 3)
            alpha = bytearray(w * h)
            j = k = 0
            for i in range(0, len(s), 4):
                delta[j] = (s[i] - 128) & 0xFF
                delta[j + 1] = (s[i + 1] - 128) & 0xFF
                delta[j + 2] = (s[i + 2] - 128) & 0xFF
                alpha[k] = s[i + 3]
                j += 3
                k += 1
            _restore(
                w,
                h,
                bytes(delta),
                bytes(alpha),
                gif_data,
                out_path,
                MODE_NAMES[mode],
                quiet=quiet,
            )

    else:
        raise ValueError(f"未知的隐写模式：{mode}")


def make_stego_gif(orig_path: str, out_path: str, quiet: bool = False) -> None:
    """把静态原图直接转成隐写 GIF（内部先转同分辨率基础 GIF），可无损还原。"""
    img = Image.open(orig_path)
    if getattr(img, "n_frames", 1) != 1:
        raise ValueError("暂不支持动图")
    base_fd, base_path = tempfile.mkstemp(suffix=".gif")
    os.close(base_fd)
    try:
        img.convert("P", palette=Image.ADAPTIVE, colors=256).save(
            base_path, format="GIF", optimize=True
        )
        encode(base_path, orig_path, out_path, quiet=quiet)
    finally:
        try:
            os.unlink(base_path)
        except OSError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="GIF 增量隐写：只藏原图比 GIF 多出的信息，可无损还原"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_enc = sub.add_parser("encode", help="编码：gif + 原图 -> 隐写 gif")
    p_enc.add_argument("gif", help="由原图转换得到的 GIF")
    p_enc.add_argument("orig", help="原图（PNG/JPEG/WebP/BMP/TIFF 等）")
    p_enc.add_argument("out", help="输出的隐写 GIF")

    p_dec = sub.add_parser("decode", help="解码：隐写 gif -> 原图")
    p_dec.add_argument("steg", help="encode 生成的隐写 GIF")
    p_dec.add_argument("out", help="还原的原图输出路径")

    args = parser.parse_args()
    try:
        if args.cmd == "encode":
            encode(args.gif, args.orig, args.out)
        else:
            decode(args.steg, args.out)
    except (ValueError, lzma.LZMAError, OSError) as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
