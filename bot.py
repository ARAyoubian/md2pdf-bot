"""
ربات تلگرام: تبدیل Markdown / متن / ZIP به PDF

نیازمند Python 3.10 یا بالاتر.

متغیرهای محیطی (همه اختیاری به‌جز BOT_TOKEN):
    BOT_TOKEN              توکن ربات
    PORT                   پورت سرور سلامت‌سنجی (پیش‌فرض 8080)
    SETTINGS_FILE          مسیر فایل تنظیمات کاربران (برای ماندگاری روی volume بگذارید)
    ALLOWED_USER_IDS       لیست آیدی عددی کاربران مجاز، جداشده با ویرگول (خالی = همه)
    PDF_PAGE_FORMAT        اندازهٔ پیش‌فرض صفحه: A4 یا Letter (پیش‌فرض A4؛ هر کاربر از منو تغییر می‌دهد)
    MAX_TEXT_BYTES         سقف حجم فایل متنی (پیش‌فرض 2MB)
    MAX_ZIP_BYTES          سقف حجم فایل ZIP (پیش‌فرض 20MB)
    MAX_ZIP_ENTRIES        سقف تعداد فایل قابل‌تبدیل در هر ZIP (پیش‌فرض 30)
    MAX_ZIP_UNCOMPRESSED   سقف مجموع حجم باز‌شدهٔ ZIP (پیش‌فرض 50MB)
    MAX_DOCX_BYTES         سقف حجم فایل Word (پیش‌فرض 20MB)
    MAX_DOCX_UNCOMPRESSED  سقف حجم باز‌شدهٔ فایل Word (پیش‌فرض 100MB)
    MAX_CONCURRENT         تعداد تبدیل همزمان (پیش‌فرض 1)
    CONVERSION_TIMEOUT     سقف زمان هر تبدیل بر حسب ثانیه (پیش‌فرض 120)
    JS_HEAP_MB             سقف حافظهٔ JS مرورگر (پیش‌فرض 192)
    ALLOW_REMOTE_IMAGES    اگر 1 باشد، تصاویر http/https داخل Markdown لود می‌شوند
"""

from md2pdf.app import main


if __name__ == "__main__":
    main()
