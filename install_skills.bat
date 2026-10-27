@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Vidcut - ติดตั้ง Claude Skills ตัดต่อ

where git >nul 2>&1
if errorlevel 1 (
  echo [X] ไม่พบ git   ติดตั้งด้วยคำสั่ง   winget install Git.Git
  echo     แล้วปิดหน้าต่างนี้ เปิดใหม่ และรันอีกครั้ง
  pause
  exit /b 1
)
set "PY="
for %%V in (3.12 3.11 3.13) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
  )
)
if not defined PY set "PY=python"

echo ติดตั้ง 8 skills (ล็อกเวอร์ชันไว้ใน tools\skills.json) ...
%PY% tools\install_skills.py install %*
pause
