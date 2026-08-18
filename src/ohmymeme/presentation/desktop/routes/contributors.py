"""贡献者 SVG 响应转换。"""

WHITE_BACKGROUND = '<rect width="100%" height="100%" fill="#ffffff"/>'


def remove_white_background(svg: str) -> str:
    """移除贡献者 SVG 的固定白色背景。"""
    return svg.replace(WHITE_BACKGROUND, "")
