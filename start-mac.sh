#!/bin/bash
# تشغيل نظام داريو النصر على ماك او لينكس
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "[1/3] تجهيز البيئة لأول مرة..."
  python3 -m venv .venv || { echo "ثبّت Python 3.12 من python.org"; exit 1; }
fi
source .venv/bin/activate
echo "[2/3] تثبيت المكتبات..."
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt || { echo "فشل تثبيت المكتبات"; exit 1; }
case "$1" in
  login) exec python -m daryo.cli login ;;
  check) exec python -m daryo.cli check ;;
esac
echo "[3/3] تشغيل نظام داريو النصر"
while true; do
  python -m daryo
  echo "توقف النظام، اعادة التشغيل بعد 15 ثانية..."
  sleep 15
done
