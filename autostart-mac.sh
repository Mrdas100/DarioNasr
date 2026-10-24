#!/bin/bash
# يشغّل النظام تلقائيا عند تسجيل الدخول ويعيد تشغيله اذا توقف (launchd)
DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.daryo.alnasr.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$DIR/data"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.daryo.alnasr</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$DIR/start-mac.sh</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$DIR/data/service.log</string>
  <key>StandardErrorPath</key><string>$DIR/data/service.log</string>
</dict></plist>
PL
launchctl unload "$PLIST" 2>/dev/null
launchctl load "$PLIST" && echo "تم: النظام يعمل الآن وسيبدأ تلقائيا مع كل تسجيل دخول. السجل: data/service.log"
echo "للإلغاء: launchctl unload $PLIST"
