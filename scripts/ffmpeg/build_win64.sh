#!/usr/bin/env bash
# 交叉编译裁剪版 ffmpeg（win64 静态单文件）——TG 导入 webm->webp 专用
# CI: .github/workflows/ffmpeg-win64.yml 缓存未命中时执行；本地可在 WSL/MSYS2 复跑
# 产物: build/ffmpeg-win64/out/ffmpeg.exe（build.py ensure_ffmpeg 从工作区
#       ffmpeg-win64/ 或本路径拾取，见 scripts/build.py）
set -euo pipefail

FFMPEG_VERSION="7.1"
FFMPEG_SHA256="40973d44970dbc83ef302b0609f2e74982be2d85916dd2ee7472d30678a7abe6"
LIBVPX_VERSION="1.14.1"
LIBVPX_SHA256="901747254d80a7937c933d03bd7c5d41e8e6c883e0665fadcb172542167c7977"
LIBWEBP_VERSION="1.4.0"
LIBWEBP_SHA256="61f873ec69e3be1b99535634340d5bde750b2e4447caa1db9f61be3fd49ab1e5"

FFMPEG_URL="https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.xz"
# GitHub archive 无生成的 configure，故用官方发布 tarball
LIBVPX_URL="https://github.com/webmproject/libvpx/archive/refs/tags/v${LIBVPX_VERSION}.tar.gz"
LIBWEBP_URL="https://storage.googleapis.com/downloads.webmproject.org/releases/webp/libwebp-${LIBWEBP_VERSION}.tar.gz"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$ROOT/build/ffmpeg-win64"
SRC="$WORK/src"
PREFIX="$WORK/prefix"
DL="$WORK/dl"
OUT="$WORK/out"
JOBS="${JOBS:-$(nproc 2>/dev/null || echo 4)}"
# 单文件预算：超出即失败（安装包增量控制，见计划验收标准）
SIZE_LIMIT=$((20 * 1024 * 1024))

die() { echo "ERROR: $*" >&2; exit 1; }

fetch() { # <url> <sha256> <dest>
    local url="$1" sha="$2" dest="$3"
    if [ -f "$dest" ] && ! echo "$sha  $dest" | sha256sum -c --quiet -; then
        echo "checksum mismatch, re-downloading: $dest"
        rm -f "$dest"
    fi
    [ -f "$dest" ] || curl -fL --retry 3 --retry-delay 2 -o "$dest" "$url"
    echo "$sha  $dest" | sha256sum -c - || die "sha256 mismatch: $dest"
}

build_libvpx() {
    [ -f "$PREFIX/lib/libvpx.a" ] && return 0
    echo "== libvpx ${LIBVPX_VERSION} =="
    tar -xzf "$DL/libvpx.tar.gz" -C "$SRC"
    cd "$SRC/libvpx-${LIBVPX_VERSION}"
    ./configure --target=x86_64-win64-gcc --prefix="$PREFIX" \
        --disable-examples --disable-tools --disable-unit-tests --disable-docs \
        --disable-vp8 --enable-static --disable-shared --enable-small
    make -j"$JOBS"
    make install
}

build_libwebp() {
    [ -f "$PREFIX/lib/libwebp.a" ] && return 0
    echo "== libwebp ${LIBWEBP_VERSION} =="
    tar -xzf "$DL/libwebp.tar.gz" -C "$SRC"
    cd "$SRC/libwebp-${LIBWEBP_VERSION}"
    # libwebpmux 必须保留：ffmpeg libwebp_anim 编码器依赖 libwebpmux >= 0.4.0
    ./configure --host=x86_64-w64-mingw32 --prefix="$PREFIX" \
        --disable-shared --enable-static \
        --disable-libwebpdemux \
        --disable-png --disable-jpeg --disable-tiff --disable-gif --disable-wic \
        --disable-gl --disable-sdl
    make -j"$JOBS"
    make install
}

build_ffmpeg() {
    [ -f "$OUT/ffmpeg.exe" ] && return 0
    echo "== ffmpeg ${FFMPEG_VERSION} =="
    tar -xJf "$DL/ffmpeg.tar.xz" -C "$SRC"
    cd "$SRC/ffmpeg-${FFMPEG_VERSION}"
    export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
    # 只开 TG 转换所需组件（matroska 解封装 / libvpx-vp9 解码 / webp 动画编码 /
    # scale 滤镜 / file 协议），其余全部 --disable-everything
    ./configure \
        --prefix="$PREFIX" \
        --target-os=win64 --arch=x86_64 --cross-prefix=x86_64-w64-mingw32- \
        --pkg-config-flags=--static \
        --extra-cflags="-I$PREFIX/include" \
        --extra-ldflags="-static -L$PREFIX/lib" \
        --disable-everything \
        --disable-autodetect \
        --disable-doc --disable-debug \
        --disable-ffplay --disable-ffprobe \
        --disable-network \
        --enable-libvpx --enable-libwebp \
        --enable-decoder=libvpx_vp9 \
        --enable-encoder=libwebp \
        --enable-encoder=libwebp_anim \
        --enable-parser=vp9 \
        --enable-demuxer=matroska \
        --enable-muxer=webp \
        --enable-filter=scale \
        --enable-protocol=file \
        --enable-bsf=vp9_superframe
    make -j"$JOBS"
    mkdir -p "$OUT"
    cp ffmpeg.exe "$OUT/ffmpeg.exe"
}

verify_exe() {
    local exe="$OUT/ffmpeg.exe"
    [ -f "$exe" ] || die "missing $exe"
    # 必须单文件自含：出现依赖 DLL 名即静态链接失败
    local imports
    imports=$(x86_64-w64-mingw32-objdump -p "$exe" | awk '/DLL Name/{print $3}')
    echo "imported DLLs: $(echo $imports)"
    if echo "$imports" | grep -qiE 'winpthread|libgcc|libstdc|libvpx|libwebp'; then
        die "ffmpeg.exe depends on non-system DLLs, static link failed"
    fi
    local size
    size=$(stat -c%s "$exe")
    echo "ffmpeg.exe size: $size bytes"
    if [ "$size" -gt "$SIZE_LIMIT" ]; then
        die "ffmpeg.exe exceeds ${SIZE_LIMIT} bytes budget (got $size)"
    fi
    # 组件存在性（与 build.py verify_ffmpeg_bundle 同口径）
    "$exe" -hide_banner -decoders | grep -q 'libvpx-vp9' || die "missing decoder libvpx-vp9"
    "$exe" -hide_banner -encoders | grep -q 'libwebp_anim' || die "missing encoder libwebp_anim"
    echo "OK: $exe"
}

mkdir -p "$DL" "$SRC" "$PREFIX" "$OUT"
fetch "$FFMPEG_URL" "$FFMPEG_SHA256" "$DL/ffmpeg.tar.xz"
fetch "$LIBVPX_URL" "$LIBVPX_SHA256" "$DL/libvpx.tar.gz"
fetch "$LIBWEBP_URL" "$LIBWEBP_SHA256" "$DL/libwebp.tar.gz"
build_libvpx
build_libwebp
build_ffmpeg
verify_exe
