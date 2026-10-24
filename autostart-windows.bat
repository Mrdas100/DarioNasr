@echo off
chcp 65001 >nul
cd /d "%~dp0"
schtasks /create /tn "DaryoAlnasr" /tr "cmd /c start \"Daryo\" /min \"%~dp0start-windows.bat\"" /sc onlogon /rl limited /f
if %errorlevel%==0 (echo تم: النظام سيعمل تلقائيا عند كل تسجيل دخول للجهاز) else (echo تعذر انشاء المهمة)
echo للإلغاء: schtasks /delete /tn DaryoAlnasr /f
pause
