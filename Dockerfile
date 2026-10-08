FROM mcr.microsoft.com/playwright/python:v1.63.0-jammy

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN id -u pwuser >/dev/null 2>&1 || useradd -m -s /bin/bash pwuser

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=pwuser:pwuser bot.py .
RUN mkdir -p /data && chown -R pwuser:pwuser /app /data

USER pwuser

RUN python bot.py --fetch-assets

ENV SETTINGS_FILE=/data/user_settings.json
VOLUME ["/data"]

EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/' % os.environ.get('PORT','8080'), timeout=3)"

CMD ["python", "bot.py"]
