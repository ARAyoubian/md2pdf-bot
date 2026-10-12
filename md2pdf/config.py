"""md2pdf.config"""
from pathlib import Path
import asyncio
import logging
import os
import re



BOT_VERSION = "r42-infinity"



logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)


logging.getLogger("httpx").setLevel(logging.WARNING)


logger = logging.getLogger("md2pdf")




# ───────────────────────────── تنظیمات ─────────────────────────────

def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default




BASE_DIR = Path(__file__).resolve().parent.parent


ASSETS_DIR = BASE_DIR / "assets"


SETTINGS_FILE = os.environ.get("SETTINGS_FILE", "user_settings.json")



MAX_TEXT_BYTES = _env_int("MAX_TEXT_BYTES", 2 * 1024 * 1024)


MAX_ZIP_BYTES = _env_int("MAX_ZIP_BYTES", 20 * 1024 * 1024)


MAX_ZIP_ENTRIES = _env_int("MAX_ZIP_ENTRIES", 30)


MAX_DOCX_BYTES = _env_int("MAX_DOCX_BYTES", 20 * 1024 * 1024)


MAX_DOCX_UNCOMPRESSED = _env_int("MAX_DOCX_UNCOMPRESSED", 100 * 1024 * 1024)


MAX_ZIP_UNCOMPRESSED = _env_int("MAX_ZIP_UNCOMPRESSED", 50 * 1024 * 1024)
MAX_IMAGE_BYTES = _env_int("MAX_IMAGE_BYTES", 5 * 1024 * 1024)
MAX_IMAGES_TOTAL = _env_int("MAX_IMAGES_TOTAL", 30 * 1024 * 1024)
IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}


MAX_CONCURRENT = max(1, _env_int("MAX_CONCURRENT", 1))


CONVERSION_TIMEOUT = _env_int("CONVERSION_TIMEOUT", 120)


RENDER_TIMEOUT_MS = 60_000


JS_HEAP_MB = _env_int("JS_HEAP_MB", 192)


TELEGRAM_UPLOAD_LIMIT = 49 * 1024 * 1024


PDF_PAGE_FORMAT = os.environ.get("PDF_PAGE_FORMAT", "A4")


FONT_SIZES = ("small", "normal", "large")


ACCENTS = {
    "blue": "#0969da",
    "green": "#1a7f37",
    "purple": "#7c3aed",
    "red": "#cf222e",
    "gray": "#444444",
}


ACCENT_LABELS = {"blue": "🔵 آبی", "green": "🟢 سبز", "purple": "🟣 بنفش", "red": "🔴 قرمز", "gray": "⚫ خاکستری"}


ACCENTS.update({
    "teal": "#0f766e",
    "orange": "#c2410c",
    "indigo": "#4338ca",
    "rose": "#be123c",
})


ACCENT_LABELS.update({
    "teal": "🩵 فیروزه‌ای",
    "orange": "🟠 نارنجی",
    "indigo": "🔷 نیلی",
    "rose": "🌹 رز",
})


BRAND_NAME = "Medoxin"


CHANNEL_HANDLE = "@Med402"


CHANNEL_URL = "https://t.me/Med402"


BRAND_FOOTER = f"{BRAND_NAME} · {CHANNEL_HANDLE}"


LOGO_CANDIDATES = (BASE_DIR / "medoxin_logo.png", BASE_DIR / "medoxin_logo.jpg")


ALLOW_REMOTE_IMAGES = os.environ.get("ALLOW_REMOTE_IMAGES", "0") == "1"


DEBUG_ERRORS = os.environ.get("DEBUG_ERRORS", "0") == "1"



ALLOWED_USER_IDS = {
    int(x)
    for x in re.split(r"[,\s]+", os.environ.get("ALLOWED_USER_IDS", ""))
    if x.strip().isdigit()
}



TEXT_EXTENSIONS = (".md", ".markdown", ".txt")



conversion_semaphore = asyncio.Semaphore(MAX_CONCURRENT)


_active_users = set()
