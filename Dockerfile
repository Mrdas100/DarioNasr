FROM python:3.12-slim
# Raqm + FriBiDi + HarfBuzz لتشكيل العربية الصحيح
RUN apt-get update && apt-get install -y --no-install-recommends libraqm0 libfribidi0 libharfbuzz0b libfreetype6 ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python deploy/fetch_emoji.py assets/emoji
ENV PYTHONUNBUFFERED=1 DATA_DIR=/app/data TG_SESSION=/app/data/daryo_user
RUN python -c "from PIL import features; assert features.check('raqm'), 'raqm missing'"
HEALTHCHECK --interval=5m --timeout=20s --start-period=3m CMD python -m daryo.cli health || exit 1
CMD ["python", "-m", "daryo"]
