"""md2pdf.settings_store"""
import json
import os
import tempfile
import threading
from md2pdf.config import (PDF_PAGE_FORMAT, SETTINGS_FILE, logger)


# ───────────────────────────── تنظیمات کاربران ─────────────────────────────

_settings_lock = threading.Lock()


def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        logger.exception("خواندن فایل تنظیمات ناموفق بود")
        return {}


def save_settings(settings):
    try:
        directory = os.path.dirname(os.path.abspath(SETTINGS_FILE))
        os.makedirs(directory, exist_ok=True)
        with _settings_lock:
            fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False)
            os.replace(tmp_path, SETTINGS_FILE)
    except Exception:
        logger.exception("ذخیرهٔ فایل تنظیمات ناموفق بود")


user_all_settings = load_settings()


def get_user_setting(chat_id, key, default):
    return user_all_settings.get(str(chat_id), {}).get(key, default)


def set_user_setting(chat_id, key, value):
    user_all_settings.setdefault(str(chat_id), {})[key] = value
    save_settings(user_all_settings)


def get_output_format(chat_id):
    return get_user_setting(chat_id, "output", "pdf")


def get_conversion_settings(chat_id):
    return {
        "orientation": get_user_setting(chat_id, "orientation", "portrait"),
        "compact": get_user_setting(chat_id, "compact", False),
        "columns": get_user_setting(chat_id, "columns", 1),
        "page_format": get_user_setting(chat_id, "page_format", PDF_PAGE_FORMAT),
        "font_size": get_user_setting(chat_id, "font_size", "normal"),
        "print_mode": get_user_setting(chat_id, "print_mode", False),
        "accent": get_user_setting(chat_id, "accent", "blue"),
        "front": get_user_setting(chat_id, "front", True),
        "paper": get_user_setting(chat_id, "paper", True),
    }
