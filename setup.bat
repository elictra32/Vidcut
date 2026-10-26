@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Vidcut - ติดตั้ง
call :refreshpath

echo.
echo ===== Vidcut setup =====
echo.

rem --- 1) Python: ใช้ 3.12 ก่อน ถ้าไม่มีลอง 3.11 แล้วค่อย 3.13 ---------------
set "PY="
for %%V in (3.12 3.11 3.13) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
  )
)
if not defined PY (
  echo [X] ไม่พบ Python 3.12 หรือ 3.11
  echo     ติดตั้งด้วยคำสั่ง   winget install Python.Python.3.12
  echo     แล้วปิดหน้าต่างนี้ เปิดใหม่ และรัน setup.bat อีกครั้ง
  goto :fail
)
echo [OK] Python: %PY%

rem --- 2) ffmpeg -----------------------------------------------------------
where ffmpeg >nul 2>&1
if errorlevel 1 (
  echo กำลังติดตั้ง ffmpeg ด้วย winget ...
  winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
  call :refreshpath
)
where ffmpeg >nul 2>&1
if errorlevel 1 (
  echo [X] ยังไม่พบ ffmpeg ในเครื่อง
  echo     ถ้าเพิ่งติดตั้ง ให้ปิดหน้าต่างนี้ เปิดใหม่ แล้วรัน setup.bat อีกครั้ง
  goto :fail
)
ffmpeg -hide_banner -filters 2>nul | findstr /c:" subtitles " >nul
if errorlevel 1 (
  echo [!] ffmpeg ตัวนี้ไม่มี libass จึงฝังซับลงวิดีโอไม่ได้
  echo     ลองติดตั้งตัวเต็ม   winget install --id Gyan.FFmpeg -e
)
echo [OK] ffmpeg

rem --- 3) สภาพแวดล้อม Python และไลบรารี ----------------------------------
if not exist ".venv\Scripts\python.exe" (
  echo กำลังสร้างสภาพแวดล้อม Python ...
  %PY% -m venv .venv
  if errorlevel 1 goto :fail
)
echo กำลังติดตั้งไลบรารี ขั้นตอนนี้ใช้เวลาสักครู่ ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 goto :fail

echo.
echo ===== ติดตั้งเสร็จแล้ว ดับเบิลคลิก run.bat เพื่อเปิดโปรแกรม =====
echo ครั้งแรกที่ถอดเสียง โปรแกรมจะดาวน์โหลดโมเดล Whisper ใช้อินเทอร์เน็ตและพื้นที่ราว 3 GB
pause
exit /b 0

:fail
echo.
echo การติดตั้งไม่สำเร็จ ดูข้อความด้านบน หรืออ่าน README.md หัวข้อ แก้ปัญหา
pause
exit /b 1

:refreshpath
rem winget changes PATH for new shells only. Re-read the user PATH from the registry and add winget's
rem Links folder, so a tool installed a moment ago is found without reopening this window.
set "USRPATH="
for /f "tokens=2,*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "USRPATH=%%B"
call set "PATH=%PATH%;%USRPATH%;%LOCALAPPDATA%\Microsoft\WinGet\Links"
exit /b 0
