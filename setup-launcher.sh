#!/usr/bin/env bash
# One-time: drop a double-clickable "Skill Factory.command" on the Desktop, with an icon.
# The launcher always installs; the icon is best-effort (needs PIL + iconutil + Xcode CLT Rez).
set -euo pipefail
cd "$(dirname "$0")"

DEST="$HOME/Desktop/Skill Factory.command"
cp launcher/skill-factory.command "$DEST"
chmod +x "$DEST"
echo "Launcher installed: $DEST"

# --- icon (best-effort) ---
if ! python3 mkicon.py; then echo "icon: PIL missing, skipped"; exit 0; fi
command -v iconutil >/dev/null || { echo "icon: iconutil missing, skipped"; exit 0; }

ICONSET=assets/icon.iconset
rm -rf "$ICONSET"; mkdir -p "$ICONSET"
ok=1
for sz in 16 32 128 256 512; do
  sips -z "$sz" "$sz" assets/icon.png --out "$ICONSET/icon_${sz}x${sz}.png" >/dev/null 2>&1 || ok=0
  d=$((sz * 2))
  sips -z "$d" "$d" assets/icon.png --out "$ICONSET/icon_${sz}x${sz}@2x.png" >/dev/null 2>&1 || ok=0
done

if [ "$ok" = 1 ] && iconutil -c icns "$ICONSET" -o assets/icon.icns 2>/dev/null; then
  if command -v Rez >/dev/null && command -v SetFile >/dev/null; then
    cp assets/icon.icns assets/_tmp.icns
    sips -i assets/_tmp.icns >/dev/null 2>&1 || true
    DeRez -only icns assets/_tmp.icns > assets/_tmp.rsrc 2>/dev/null || true
    if Rez -append assets/_tmp.rsrc -o "$DEST" 2>/dev/null && SetFile -a C "$DEST" 2>/dev/null; then
      echo "icon attached to launcher"
    else
      echo "icon built (assets/icon.icns) but attach step skipped"
    fi
    rm -f assets/_tmp.icns assets/_tmp.rsrc
  fi
else
  echo "icns build skipped (sips/iconutil)"
fi
rm -rf "$ICONSET"
