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

clean() {
    rm -rf "$DIST_DIR/OhMyMeme.AppDir" "$DIST_DIR/*.AppImage" \
           "$DIST_DIR/*.deb" "$DIST_DIR/*.rpm"
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
        wget -q "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" \
            -O "$DIST_DIR/appimagetool"
        chmod +x "$DIST_DIR/appimagetool"
    fi

    cd "$DIST_DIR"
    ARCH=x86_64 ./appimagetool OhMyMeme.AppDir \
        "OhMyMeme-v${APP_VERSION}-x86_64.AppImage"
    echo "AppImage: $DIST_DIR/OhMyMeme-v${APP_VERSION}-x86_64.AppImage"
}

# 3. 构建 .deb
build_deb() {
    local deb_root="$DIST_DIR/ohmymeme_${APP_VERSION}_amd64"
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
Description: 轻量化跨平台表情包管理系统
 轻量化表情包管理器，支持快捷键呼出、搜索、一键复制到剪贴板。
CTRL

    # 替换版本号
    sed -i "s/Version: 0.1.0/Version: $APP_VERSION/" "$deb_root/DEBIAN/control"

    dpkg-deb --build "$deb_root"
    mv "$DIST_DIR/ohmymeme_${APP_VERSION}_amd64.deb" \
       "$DIST_DIR/OhMyMeme-v${APP_VERSION}-amd64.deb"
    echo "deb:  $DIST_DIR/OhMyMeme-v${APP_VERSION}-amd64.deb"
}

# 4. 构建 .rpm
build_rpm() {
    local rpm_root="$DIST_DIR/rpmbuild"
    mkdir -p "$rpm_root/BUILD" "$rpm_root/RPMS" "$rpm_root/SOURCES" \
             "$rpm_root/SPECS" "$rpm_root/SRPMS"

    local src_tar="$DIST_DIR/ohmymeme-${APP_VERSION}.tar.gz"
    cd "$DIST_DIR"
    tar czf "$src_tar" OhMyMeme/

    cat > "$rpm_root/SPECS/ohmymeme.spec" << 'SPEC'
Name: ohmymeme
Version: 0.1.0
Release: 1%{?dist}
Summary: 轻量化跨平台表情包管理系统
License: MIT
URL: https://github.com/ohmymeme/ohmymeme
Source0: ohmymeme-0.1.0.tar.gz

%description
轻量化表情包管理器，支持快捷键呼出、搜索、一键复制到剪贴板。

%prep
%setup -q

%install
mkdir -p %{buildroot}/%{_bindir}
cp -r OhMyMeme/_internal %{buildroot}/%{_bindir}/
cp OhMyMeme/OhMyMeme %{buildroot}/%{_bindir}/
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

    sed -i "s/Version: 0.1.0/Version: $APP_VERSION/" "$rpm_root/SPECS/ohmymeme.spec"

    rpmbuild --define "_topdir $rpm_root" -bb "$rpm_root/SPECS/ohmymeme.spec"
    cp "$rpm_root/RPMS/x86_64/"*.rpm "$DIST_DIR/"
    echo "rpm:  $DIST_DIR/*.rpm"
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
            echo ""
            echo "=== 构建完成 ==="
            echo "AppImage: $DIST_DIR/OhMyMeme-v${APP_VERSION}-x86_64.AppImage"
            echo "deb:      $DIST_DIR/OhMyMeme-v${APP_VERSION}-amd64.deb"
            ;;
    esac
}

main "$@"
