#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APP_DIR"
cat > "$APP_DIR/capricorn.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Капри
Comment=Локальный голосовой помощник
Exec=/usr/bin/env bash "$ROOT/run-linux.sh"
Path=$ROOT
Icon=$ROOT/assets/poses/capri.png
Terminal=false
Categories=Utility;Accessibility;
StartupNotify=false
EOF
chmod +x "$APP_DIR/capricorn.desktop"
echo "Добавила Капри в меню приложений KDE. Автозапуск не включён."
