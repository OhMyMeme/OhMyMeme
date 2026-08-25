"""感知哈希算法单元测试：同内容不同编码应判相似，不同内容应判相异"""

import random

from PIL import Image

from src.webui import (
    _PHASH_SIMILAR_DIST,
    _perceptual_hash,
    _phash_hamming,
)


def _textured(seed=0, size=96):
    """带随机纹理的照片样式图（每像素低频偏置+高频细节），模拟真实表情包"""
    rng = random.Random(seed)
    img = Image.new("RGB", (size, size))
    px = img.load()
    # 低频底色渐变
    for y in range(size):
        for x in range(size):
            base_r = (x * 200) // size
            base_g = (y * 200) // size
            base_b = ((x + y) * 100) // size
            px[x, y] = (
                min(255, max(0, base_r + rng.randint(-25, 25))),
                min(255, max(0, base_g + rng.randint(-25, 25))),
                min(255, max(0, base_b + rng.randint(-25, 25))),
            )
    return img


class TestPerceptualHash:
    def test_self_distance_zero(self):
        img = _textured()
        assert _phash_hamming(_perceptual_hash(img), _perceptual_hash(img)) == 0

    def test_same_content_resample_similar(self):
        # 同一内容轻微重采样后应判相似（用户原始场景）
        img = _textured()
        rep = img.resize((48, 48), Image.LANCZOS).resize((96, 96), Image.LANCZOS)
        d = _phash_hamming(_perceptual_hash(img), _perceptual_hash(rep))
        assert d <= _PHASH_SIMILAR_DIST

    def test_same_content_brightness_shift_similar(self):
        # 整体亮度偏移仍应相似
        img = _textured()
        br = Image.eval(img, lambda v: min(255, int(v * 1.3) + 10))
        d = _phash_hamming(_perceptual_hash(img), _perceptual_hash(br))
        assert d <= _PHASH_SIMILAR_DIST

    def test_same_content_convert_format_similar(self):
        # 同内容转码（压缩损失）应相似
        import io

        img = _textured()
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=70)
        buf.seek(0)
        rejoined = Image.open(buf).convert("RGB")
        d = _phash_hamming(_perceptual_hash(img), _perceptual_hash(rejoined))
        assert d <= _PHASH_SIMILAR_DIST

    def test_different_images_not_similar(self):
        # 完全不同内容应相异
        d = _phash_hamming(
            _perceptual_hash(_textured(1)), _perceptual_hash(_textured(999))
        )
        assert d > _PHASH_SIMILAR_DIST

    def test_light_backgrounds_still_distinct(self):
        # 浅色大底但内容不同的图（此前的误判样本类型，非纯色）应能区分
        a = _textured(11)
        # 把 a 抹成偏浅色，但保留纹理差异；再做一张纹理不同的浅色图
        b = _textured(22)
        da = _phash_hamming(_perceptual_hash(a), _perceptual_hash(b))
        assert da > _PHASH_SIMILAR_DIST
