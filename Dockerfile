# نسخهٔ تصویر باید دقیقاً با نسخهٔ playwright در requirements.txt یکی باشد
FROM mcr.microsoft.com/playwright/python:v1.63.0-jammy

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    LANG=C.UTF-8

# LibreOffice برای تبدیل Word به PDF و فونت‌های لازم.
# این بسته‌ها از همین حالا نصب‌اند تا برای فعال‌سازی docx → pdf نیازی به تغییر Dockerfile نباشد.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libreoffice-writer-nogui \
      fontconfig \
      fonts-dejavu-core \
      fonts-liberation \
      fonts-noto-core \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

RUN id -u pwuser >/dev/null 2>&1 || useradd -m -s /bin/bash pwuser

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# لوگو می‌تواند PNG (شفاف) یا JPG باشد؛ هر کدام که وجود داشته باشد کپی می‌شود
COPY bot.py converters.py medoxin_logo.* ./
# بخش‌های برنامه (پوشهٔ md2pdf)
COPY md2pdf/ ./md2pdf/

# دانلود assets (MathJax، Mermaid، فونت‌های Vazirmatn، قالب Word فارسی) هنگام build
RUN python bot.py --fetch-assets

# نصب فونت فارسی برای LibreOffice (و کش فونت‌ها)
RUN mkdir -p /usr/local/share/fonts/vazirmatn \
 && (cp /app/assets/fonts/Vazirmatn-Regular.ttf /app/assets/fonts/Vazirmatn-Bold.ttf /usr/local/share/fonts/vazirmatn/ \
     || echo "WARNING: static Vazirmatn fonts missing; LibreOffice will use fallback fonts") \
 && fc-cache -f || true
RUN fc-match Vazirmatn || true

RUN mkdir -p /data && chown -R pwuser:pwuser /app /data
USER pwuser

# برای ماندگار شدن تنظیمات کاربران، یک volume روی /data مونت کنید
ENV SETTINGS_FILE=/data/user_settings.json
VOLUME ["/data"]

EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/' % os.environ.get('PORT','8080'), timeout=3)"

CMD ["python", "bot.py"]
