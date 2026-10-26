@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Vidcut
call :refreshpath
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set PYTHONUTF8=1
if not defined VIDCUT_PORT set VIDCUT_PORT=8765

if not exist ".venv\Scripts\python.exe" (
  echo ยังไม่ได้ติดตั้ง กรุณาดับเบิลคลิก setup.bat ก่อน
  pause
  exit /b 1
)

echo Vidcut กำลังเปิดที่ http://127.0.0.1:%VIDCUT_PORT%
echo ปิดหน้าต่างนี้เพื่อหยุดโปรแกรม
".venv\Scripts\python.exe" -m server.app
if errorlevel 1 (
  echo.
  echo โปรแกรมหยุดทำงานผิดปกติ ดูข้อความด้านบน หรืออ่าน README.md หัวข้อ แก้ปัญหา
  pause
)
exit /b 0

:refreshpath
rem winget changes PATH for new shells only. Re-read the user PATH from the registry and add winget's
rem Links folder, so a tool installed a moment ago is found without reopening this window.
set "USRPATH="
for /f "tokens=2,*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "USRPATH=%%B"
call set "PATH=%PATH%;%USRPATH%;%LOCALAPPDATA%\Microsoft\WinGet\Links"
exit /b 0
