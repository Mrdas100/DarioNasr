@echo off
chcp 65001 >nul
title Daryo Alnasr
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist .venv (
  echo [1/3] تجهيز البيئة لأول مرة...
  %PY% -m venv .venv || (echo ثبّت Python 3.12 من python.org ثم أعد المحاولة & pause & exit /b 1)
)
call .venv\Scripts\activate.bat
echo [2/3] تثبيت المكتبات...
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt || (echo فشل تثبيت المكتبات & pause & exit /b 1)
if /i "%1"=="login" ( python -m daryo.cli login & pause & exit /b 0 )
if /i "%1"=="check" ( python -m daryo.cli check & pause & exit /b 0 )
echo [3/3] تشغيل نظام داريو النصر. اترك هذه النافذة مفتوحة او مصغرة
:loop
python -m daryo
echo توقف النظام، اعادة التشغيل بعد 15 ثانية...
timeout /t 15 /nobreak >nul
goto loop
