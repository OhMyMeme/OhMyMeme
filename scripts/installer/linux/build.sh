#!/bin/bash
# OhMyMeme Linux 打包脚本
# 支持: AppImage, .deb, .rpm
# 用法: bash build.sh [appimage|deb|rpm|all]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../../../" && pwd)"
DIST_DIR="$PROJECT_DIR/dist"
APP_NAME="OhMyMeme"
APP_VERSION="$(python3 -c "import re; print(re.search(r'__version__\s*=\s*\"([^\"]+)\"', open('$PROJECT_DIR/src/__init__.py').read())[1])")"
# deb/rpm 的 Version 字段要求数字开头；nightly 时用构建脚本传入的基础版本号
PKG_VERSION="${OHMYMEME_PKG_VERSION:-$APP_VERSION}"

# 检测架构
ARCH="${OHMYMEME_ARCH:-$(uname -m)}"
case "$ARCH" in
    x86_64|amd64)
        ARCH="x86_64"
        DEB_ARCH="amd64"
        RPM_ARCH="x86_64"
        APPIMAGE_ARCH="x86_64"
        ;;
    aarch64|arm64)
        ARCH="aarch64"
        DEB_ARCH="arm64"
        RPM_ARCH="aarch64"
        APPIMAGE_ARCH="aarch64"
        ;;
    *)
        echo "不支持的架构: $ARCH"
        exit 1
        ;;
esac

clean() {
    rm -rf "$DIST_DIR/OhMyMeme.AppDir" "$DIST_DIR"/*.AppImage \
           "$DIST_DIR"/*.deb "$DIST_DIR"/*.rpm
}

# 1. 用 PyInstaller 打包
build_pyinstaller() {
    if [ -n "${SKIP_PYINSTALLER:-}" ]; then
        return 0
    fi
    cd "$PROJECT_DIR"
    python scripts/build.py --linux --build-only
}

# 2. 构建 AppImage
build_appimage() {
    local appdir="$DIST_DIR/OhMyMeme.AppDir"
    mkdir -p "$appdir/usr/bin"
    mkdir -p "$appdir/usr/share/applications"
    mkdir -p "$appdir/usr/share/icons/hicolor/256x256/apps"

    # 复制 PyInstaller 输出
    cp -r "$DIST_DIR/OhMyMeme/_internal" "$appdir/usr/bin/"
    cp "$DIST_DIR/OhMyMeme/OhMyMeme" "$appdir/usr/bin/"
    ln -sf "$appdir/usr/bin/OhMyMeme" "$appdir/AppRun"

    # .desktop 文件
    cat > "$appdir/usr/share/applications/com.ohmymeme.desktop" << 'DESKTOP'
[Desktop Entry]
Name=OhMyMeme
Comment=轻量化跨平台表情包管理系统
Exec=OhMyMeme
Icon=com.ohmymeme
Terminal=false
Type=Application
Categories=Utility;Graphics;
DESKTOP
    cp "$appdir/usr/share/applications/com.ohmymeme.desktop" "$appdir/"

    # 图标
    cat > /tmp/gen_icon.py << 'PYEOF'
from PIL import Image, ImageDraw
img = Image.new('RGBA', (256, 256), (255, 100, 100, 255))
draw = ImageDraw.Draw(img)
draw.ellipse([36, 36, 220, 220], fill=(74, 158, 255, 255))
draw.text((80, 100), "OM", fill=(255, 255, 255, 255))
img.save('/tmp/com.ohmymeme.png')
PYEOF
    python3 /tmp/gen_icon.py
    cp /tmp/com.ohmymeme.png "$appdir/usr/share/icons/hicolor/256x256/apps/"
    cp /tmp/com.ohmymeme.png "$appdir/"

    # 下载 appimagetool
    if [ ! -f "$DIST_DIR/appimagetool" ]; then
        wget -q "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-${APPIMAGE_ARCH}.AppImage" \
            -O "$DIST_DIR/appimagetool"
        chmod +x "$DIST_DIR/appimagetool"
    fi

    cd "$DIST_DIR"
    ARCH=$APPIMAGE_ARCH ./appimagetool --appimage-extract-and-run OhMyMeme.AppDir \
        "OhMyMeme-v${APP_VERSION}-${ARCH}.AppImage"
    echo "AppImage: $DIST_DIR/OhMyMeme-v${APP_VERSION}-${ARCH}.AppImage"
}

# 3. 构建 .deb
build_deb() {
    local deb_root="$DIST_DIR/ohmymeme_${APP_VERSION}_${DEB_ARCH}"
    mkdir -p "$deb_root/DEBIAN"
    mkdir -p "$deb_root/usr/bin"
    mkdir -p "$deb_root/usr/share/applications"
    mkdir -p "$deb_root/usr/share/icons/hicolor/256x256/apps"

    cp -r "$DIST_DIR/OhMyMeme/_internal" "$deb_root/usr/bin/"
    cp "$DIST_DIR/OhMyMeme/OhMyMeme" "$deb_root/usr/bin/"
    ln -sf /usr/bin/OhMyMeme "$deb_root/usr/bin/ohmymeme"

    cat > "$deb_root/usr/share/applications/com.ohmymeme.desktop" << 'DESKTOP'
[Desktop Entry]
Name=OhMyMeme
Comment=轻量化跨平台表情包管理系统
Exec=ohmymeme
Icon=com.ohmymeme
Terminal=false
Type=Application
Categories=Utility;Graphics;
DESKTOP

    cp /tmp/com.ohmymeme.png "$deb_root/usr/share/icons/hicolor/256x256/apps/"

    cat > "$deb_root/DEBIAN/control" << 'CTRL'
Package: ohmymeme
Version: 0.1.0
Section: utils
Priority: optional
Architecture: amd64
Maintainer: OhMyMeme Team
Depends: python3-gi, gir1.2-webkit2-4.1 | gir1.2-webkit2-4.0
Description: 轻量化跨平台表情包管理系统
 轻量化表情包管理器，支持快捷键呼出、搜索、一键复制到剪贴板。
CTRL

    # 替换版本号和架构（deb 要求数字开头，nightly 用 PKG_VERSION）
    sed -i "s/Version: 0.1.0/Version: $PKG_VERSION/" "$deb_root/DEBIAN/control"
    sed -i "s/Architecture: amd64/Architecture: $DEB_ARCH/" "$deb_root/DEBIAN/control"

    dpkg-deb --build "$deb_root"
    mv "$DIST_DIR/ohmymeme_${APP_VERSION}_${DEB_ARCH}.deb" \
       "$DIST_DIR/OhMyMeme-v${APP_VERSION}-${DEB_ARCH}.deb"
    echo "deb:  $DIST_DIR/OhMyMeme-v${APP_VERSION}-${DEB_ARCH}.deb"
}

# 4. 构建 .rpm
build_rpm() {
    local rpm_root="$DIST_DIR/rpmbuild"
    rm -rf "$rpm_root"
    mkdir -p "$rpm_root/BUILD" "$rpm_root/RPMS" "$rpm_root/SOURCES" \
             "$rpm_root/SPECS" "$rpm_root/SRPMS"

    local src_tar="$rpm_root/SOURCES/ohmymeme-${PKG_VERSION}.tar.gz"
    cd "$DIST_DIR"
    tar czf "$src_tar" OhMyMeme/

    cat > "$rpm_root/SPECS/ohmymeme.spec" << 'SPEC'
# 关闭 debuginfo 子包：部分 rpm 版本会额外产出 ohmymeme-debuginfo-*.rpm，
# 与主包一起匹配通配符会让后面的 mv 把目标当成目录而失败。
%global debug_package %{nil}

Name: ohmymeme
Version: 0.1.0
Release: 1%{?dist}
Summary: 轻量化跨平台表情包管理系统
License: MIT
URL: https://github.com/OhMyMeme/OhMyMeme
Source0: ohmymeme-0.1.0.tar.gz

%description
轻量化表情包管理器，支持快捷键呼出、搜索、一键复制到剪贴板。

%prep
%setup -q -n OhMyMeme

%install
mkdir -p %{buildroot}/%{_bindir}
cp -r _internal %{buildroot}/%{_bindir}/
cp OhMyMeme %{buildroot}/%{_bindir}/
ln -sf %{_bindir}/OhMyMeme %{buildroot}/%{_bindir}/ohmymeme

%files
%{_bindir}/*
%doc

%post
cat > /usr/share/applications/com.ohmymeme.desktop << EOF
[Desktop Entry]
Name=OhMyMeme
Comment=轻量化跨平台表情包管理系统
Exec=ohmymeme
Icon=com.ohmymeme
Terminal=false
Type=Application
Categories=Utility;Graphics;
EOF
SPEC

    sed -i "s/Version: 0.1.0/Version: $PKG_VERSION/" "$rpm_root/SPECS/ohmymeme.spec"
    sed -i "s/Source0: ohmymeme-0.1.0.tar.gz/Source0: ohmymeme-${PKG_VERSION}.tar.gz/" "$rpm_root/SPECS/ohmymeme.spec"

    rpmbuild --define "_topdir $rpm_root" -bb "$rpm_root/SPECS/ohmymeme.spec"

    # 只取主包（ohmymeme-<数字版本>...），避免把 debuginfo 等附加包一起移动
    local built_rpm
    built_rpm="$(find "$rpm_root/RPMS/$RPM_ARCH" -maxdepth 1 \
        -name 'ohmymeme-[0-9]*.rpm' -print -quit)"
    if [ -z "$built_rpm" ]; then
        echo "未找到 RPM 产物: $rpm_root/RPMS/$RPM_ARCH" >&2
        return 1
    fi
    mv "$built_rpm" "$DIST_DIR/OhMyMeme-v${APP_VERSION}-${RPM_ARCH}.rpm"
    echo "rpm:  $DIST_DIR/OhMyMeme-v${APP_VERSION}-${RPM_ARCH}.rpm"
}

main() {
    local target="${1:-all}"
    clean

    case "$target" in
        appimage)
            build_pyinstaller
            build_appimage
            ;;
        deb)
            build_pyinstaller
            build_deb
            ;;
        rpm)
            build_pyinstaller
            build_rpm
            ;;
        all|*)
            build_pyinstaller
            build_appimage
            build_deb
            build_rpm
            echo ""
            echo "=== 构建完成 ==="
            echo "AppImage: $DIST_DIR/OhMyMeme-v${APP_VERSION}-${ARCH}.AppImage"
            echo "deb:      $DIST_DIR/OhMyMeme-v${APP_VERSION}-${DEB_ARCH}.deb"
            echo "rpm:      $DIST_DIR/OhMyMeme-v${APP_VERSION}-${RPM_ARCH}.rpm"
            ;;
    esac
}

main "$@"
