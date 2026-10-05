# نسخهٔ تصویر باید دقیقاً با نسخهٔ playwright در requirements.txt یکی باشد
FROM mcr.microsoft.com/playwright/python:v1.63.0-jammy

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# کاربر غیر root (در ایمیج رسمی معمولاً pwuser وجود دارد؛ اگر نبود ساخته می‌شود)
RUN id -u pwuser >/dev/null 2>&1 || useradd -m -s /bin/bash pwuser

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=pwuser:pwuser bot.py .
RUN mkdir -p /data && chown -R pwuser:pwuser /app /data

USER pwuser

# دانلود MathJax، Mermaid و فونت Vazirmatn هنگام build تا ربات به CDN وابسته نباشد
RUN python bot.py --fetch-assets

# برای ماندگار شدن تنظیمات کاربران، یک volume روی /data مونت کنید
ENV SETTINGS_FILE=/data/user_settings.json
VOLUME ["/data"]

EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/' % os.environ.get('PORT','8080'), timeout=3)"

CMD ["python", "bot.py"]
