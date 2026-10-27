#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VERSION="${1:-0.1.0}"
BUILD_DIR="$ROOT/build/packages"
APPDIR="$BUILD_DIR/AppDir"
PAYLOAD="$BUILD_DIR/payload"

rm -rf "$BUILD_DIR"
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/applications" \
  "$APPDIR/usr/share/icons/hicolor/256x256/apps" "$PAYLOAD/opt/capricorn" \
  "$PAYLOAD/usr/bin" "$PAYLOAD/usr/share/applications" \
  "$PAYLOAD/usr/share/icons/hicolor/256x256/apps"
cp -a "$ROOT/dist/capricorn" "$APPDIR/usr/lib/capricorn"
cp "$ROOT/packaging/AppRun" "$APPDIR/AppRun"
cp "$ROOT/packaging/capricorn.desktop" "$APPDIR/usr/share/applications/capricorn.desktop"
cp "$ROOT/assets/poses/capri.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/capricorn.png"
cp "$ROOT/LICENSE" "$APPDIR/LICENSE"
chmod +x "$APPDIR/AppRun"

cat > "$APPDIR/capricorn.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Capri
Name[ru]=Капри
Comment=Local voice assistant
Comment[ru]=Локальный голосовой помощник
Exec=AppRun
Icon=capricorn
Terminal=false
Categories=Utility;Accessibility;
StartupNotify=false
EOF
cp "$APPDIR/usr/share/icons/hicolor/256x256/apps/capricorn.png" "$APPDIR/capricorn.png"

cp -a "$APPDIR/usr/lib/capricorn/." "$PAYLOAD/opt/capricorn/"
cat > "$PAYLOAD/usr/bin/capricorn" <<'EOF'
#!/usr/bin/env bash
exec /opt/capricorn/capricorn "$@"
EOF
chmod +x "$PAYLOAD/usr/bin/capricorn"
cp "$ROOT/packaging/capricorn.desktop" "$PAYLOAD/usr/share/applications/capricorn.desktop"
cp "$APPDIR/capricorn.png" "$PAYLOAD/usr/share/icons/hicolor/256x256/apps/capricorn.png"

fpm -s dir -t deb -n capricorn -v "$VERSION" --architecture amd64 \
  --description "Local voice assistant Capri" --license MIT \
  --depends libgl1 --depends libxkbcommon0 --depends libxkbcommon-x11-0 --depends libxcb-cursor0 \
  --depends libxcb-icccm4 --depends libxcb-image0 --depends libxcb-keysyms1 --depends libxcb-randr0 \
  --depends libxcb-render-util0 --depends libxcb-shape0 --depends libxcb-xfixes0 --depends libxcb-xinerama0 \
  --depends libxcb-xkb1 --depends libx11-xcb1 --depends libsm6 --depends libdbus-1-3 --depends espeak-ng \
  -C "$PAYLOAD" -p "$BUILD_DIR/capricorn_${VERSION}_amd64.deb" .
fpm -s dir -t rpm -n capricorn -v "$VERSION" --architecture x86_64 \
  --description "Local voice assistant Capri" --license MIT \
  --depends mesa-libGL --depends libxkbcommon --depends libxkbcommon-x11 --depends libxcb \
  --depends libX11-xcb --depends libSM --depends glib2 --depends dbus-libs --depends espeak-ng \
  -C "$PAYLOAD" -p "$BUILD_DIR/capricorn-${VERSION}-1.x86_64.rpm" .

APPIMAGETOOL="$(command -v appimagetool || true)"
if [[ -z "$APPIMAGETOOL" ]]; then
  echo "appimagetool is required to create the AppImage." >&2
  exit 1
fi
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$APPIMAGETOOL" "$APPDIR" "$BUILD_DIR/Capri-${VERSION}-x86_64.AppImage"
echo "Packages created in $BUILD_DIR"
