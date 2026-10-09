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
    MAX_CONCURRENT         تعداد تبدیل همزمان (پیش‌فرض 1)
    CONVERSION_TIMEOUT     سقف زمان هر تبدیل بر حسب ثانیه (پیش‌فرض 120)
    JS_HEAP_MB             سقف حافظهٔ JS مرورگر (پیش‌فرض 192)
    ALLOW_REMOTE_IMAGES    اگر 1 باشد، تصاویر http/https داخل Markdown لود می‌شوند
"""
import asyncio
import contextlib
import gc
import html
import io
import json
import logging
import os
import re
import secrets
import sys
import tarfile
import tempfile
import threading
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import markdown
import nh3
from playwright.async_api import async_playwright
from pygments.formatters import HtmlFormatter
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_VERSION = "r11-footer-overlay"

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


BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
SETTINGS_FILE = os.environ.get("SETTINGS_FILE", "user_settings.json")

MAX_TEXT_BYTES = _env_int("MAX_TEXT_BYTES", 2 * 1024 * 1024)
MAX_ZIP_BYTES = _env_int("MAX_ZIP_BYTES", 20 * 1024 * 1024)
MAX_ZIP_ENTRIES = _env_int("MAX_ZIP_ENTRIES", 30)
MAX_ZIP_UNCOMPRESSED = _env_int("MAX_ZIP_UNCOMPRESSED", 50 * 1024 * 1024)
MAX_CONCURRENT = max(1, _env_int("MAX_CONCURRENT", 1))
CONVERSION_TIMEOUT = _env_int("CONVERSION_TIMEOUT", 120)
RENDER_TIMEOUT_MS = 60_000
JS_HEAP_MB = _env_int("JS_HEAP_MB", 192)
TELEGRAM_UPLOAD_LIMIT = 49 * 1024 * 1024
PDF_PAGE_FORMAT = os.environ.get("PDF_PAGE_FORMAT", "A4")
FONT_SIZES = ("small", "normal", "large")
ALLOW_REMOTE_IMAGES = os.environ.get("ALLOW_REMOTE_IMAGES", "0") == "1"
DEBUG_ERRORS = os.environ.get("DEBUG_ERRORS", "0") == "1"

ALLOWED_USER_IDS = {
    int(x)
    for x in re.split(r"[,\s]+", os.environ.get("ALLOWED_USER_IDS", ""))
    if x.strip().isdigit()
}

TEXT_EXTENSIONS = (".md", ".markdown", ".txt")

CODE_STYLE_LIGHT = HtmlFormatter(style="friendly").get_style_defs(".codehilite")

conversion_semaphore = asyncio.Semaphore(MAX_CONCURRENT)
browser_lock = asyncio.Lock()
global_browser = None
playwright_instance = None
_active_users = set()


# ───────────────────── فایل‌های محلی (MathJax / Mermaid / فونت) ─────────────────────
# این فایل‌ها هنگام build با `python bot.py --fetch-assets` دانلود می‌شوند و در زمان
# رندر از روی دیسک سرو می‌شوند؛ مرورگر هیچ دسترسی اینترنتی ندارد.

ASSETS_VERSION = "1"
MATHJAX_URL = "https://registry.npmjs.org/mathjax/-/mathjax-3.2.2.tgz"
MERMAID_URL = "https://registry.npmjs.org/mermaid/-/mermaid-11.4.1.tgz"
VAZIRMATN_URL = "https://registry.npmjs.org/vazirmatn/-/vazirmatn-33.0.3.tgz"


def _download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "md2pdf-bot"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def _safe_write(root: Path, rel: str, data: bytes):
    root = root.resolve()
    dest = (root / rel).resolve()
    if root not in dest.parents:
        raise ValueError(f"مسیر نامعتبر در آرشیو: {rel}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def ensure_assets(force=False):
    marker = ASSETS_DIR / ".ready"
    if not force and marker.exists() and marker.read_text().strip() == ASSETS_VERSION:
        return
    logger.info("Downloading static assets (MathJax, Mermaid, Vazirmatn)...")
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    # MathJax
    with tarfile.open(fileobj=io.BytesIO(_download(MATHJAX_URL)), mode="r:gz") as tar:
        for member in tar:
            if not member.isfile() or not member.name.startswith("package/es5/"):
                continue
            rel = member.name[len("package/es5/"):]
            if (
                rel == "tex-chtml.js"
                or rel.startswith("output/chtml/fonts/woff-v2/")
                or rel.startswith("input/tex/extensions/")
            ):
                _safe_write(ASSETS_DIR / "mathjax", rel, tar.extractfile(member).read())

    # Mermaid
    with tarfile.open(fileobj=io.BytesIO(_download(MERMAID_URL)), mode="r:gz") as tar:
        member = tar.getmember("package/dist/mermaid.min.js")
        _safe_write(ASSETS_DIR / "mermaid", "mermaid.min.js", tar.extractfile(member).read())

    # Vazirmatn (فونت متغیر)
    fonts = {}
    with tarfile.open(fileobj=io.BytesIO(_download(VAZIRMATN_URL)), mode="r:gz") as tar:
        for member in tar:
            if member.isfile() and member.name.endswith(".woff2"):
                fonts[member.name] = tar.extractfile(member).read()
    pick = next((n for n in fonts if "wght" in n or "variable" in n.lower()), None)
    if pick is None:
        raise RuntimeError(f"فونت متغیر Vazirmatn پیدا نشد. فایل‌ها: {list(fonts)}")
    _safe_write(ASSETS_DIR / "fonts", "Vazirmatn-Variable.woff2", fonts[pick])

    required = [
        ASSETS_DIR / "mathjax" / "tex-chtml.js",
        ASSETS_DIR / "mathjax" / "input" / "tex" / "extensions" / "mhchem.js",
        ASSETS_DIR / "mermaid" / "mermaid.min.js",
        ASSETS_DIR / "fonts" / "Vazirmatn-Variable.woff2",
    ]
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise RuntimeError(f"فایل‌های لازم دانلود نشدند: {missing}")
    marker.write_text(ASSETS_VERSION)
    logger.info("Assets ready.")


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


def get_conversion_settings(chat_id):
    return {
        "orientation": get_user_setting(chat_id, "orientation", "portrait"),
        "compact": get_user_setting(chat_id, "compact", False),
        "columns": get_user_setting(chat_id, "columns", 1),
        "page_format": get_user_setting(chat_id, "page_format", PDF_PAGE_FORMAT),
        "font_size": get_user_setting(chat_id, "font_size", "normal"),
        "print_mode": get_user_setting(chat_id, "print_mode", False),
    }


# ───────────────────────────── سرور سلامت‌سنجی ─────────────────────────────

class HealthHandler(BaseHTTPRequestHandler):
    def _respond(self, with_body):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        if with_body:
            self.wfile.write(b"Bot is Running successfully on Back4App!")

    def do_GET(self):
        self._respond(True)

    def do_HEAD(self):
        self._respond(False)

    def log_message(self, *args):
        pass


def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


# ───────────────────────────── قالب HTML ─────────────────────────────

DOC_URL = "http://render.invalid/doc.html"
ASSET_PREFIX = "http://render.invalid/assets/"

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html dir="auto">
<head>
    <meta charset="utf-8">
    <style>
        @font-face {
            font-family: 'Vazirmatn';
            src: url('/assets/fonts/Vazirmatn-Variable.woff2') format('woff2');
            font-weight: 100 900;
            font-display: block;
        }

        :root {
            --bg-body: #ffffff;
            --text-main: #1f2328;
            --text-muted: #656d76;
            --bg-code: #f6f8fa;
            --border-color: #d0d7de;
            --accent-color: #0969da;
            --table-even: #fafbfc;

            --note-bg: #ddf4ff; --note-border: #0969da;
            --warning-bg: #fff8c5; --warning-border: #9a6700;
            --tip-bg: #dafbe1; --tip-border: #1a7f37;
            --important-bg: #ffebe9; --important-border: #cf222e;
        }

        body {
            background-color: var(--bg-body);
            font-family: 'Vazirmatn', 'Noto Sans Arabic', 'Segoe UI', Roboto, sans-serif;
            color: var(--text-main);
            line-height: 1.7;
            padding: 0;
            margin: 0;
            font-size: 15px;
        }

        body.columns-2 {
            column-count: 2;
            column-gap: 25px;
        }
        body.columns-2 h1 {
            column-span: all;
        }

        h1 {
            page-break-before: always;
            break-before: page;
        }
        body > h1:first-child,
        body > h1:first-of-type {
            page-break-before: avoid;
            break-before: avoid;
        }

        body.compact-mode {
            font-size: 13.5px;
            line-height: 1.45;
        }
        body.compact-mode h1 { font-size: 22px; margin-top: 16px; margin-bottom: 8px; }
        body.compact-mode h2 { font-size: 18px; margin-top: 14px; margin-bottom: 6px; }
        body.compact-mode h3 { font-size: 15px; margin-top: 10px; margin-bottom: 4px; }
        body.compact-mode p { margin-bottom: 8px; }
        body.compact-mode table th, body.compact-mode table td { padding: 6px 10px; }
        body.compact-mode pre, body.compact-mode .codehilite { padding: 10px 12px; margin: 10px 0; }

        h1, h2, h3, h4, h5, h6 {
            color: var(--text-main);
            font-weight: 600;
            line-height: 1.3;
            margin-top: 24px;
            margin-bottom: 12px;
        }

        h1 { font-size: 26px; border-bottom: 2px solid var(--border-color); padding-bottom: 8px; }
        h2 { font-size: 20px; border-bottom: 1px solid var(--border-color); padding-bottom: 6px; }
        h3 { font-size: 17px; }

        p { margin-top: 0; margin-bottom: 14px; }

        p, li, blockquote {
            text-align: justify;
            text-justify: inter-word;
        }

        img { max-width: 100%; height: auto; }

        pre, .codehilite {
            background-color: var(--bg-code) !important;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 14px 16px;
            overflow-x: auto;
            direction: ltr !important;
            text-align: left !important;
            unicode-bidi: normal !important;
            font-family: 'DejaVu Sans Mono', 'Liberation Mono', Menlo, Consolas, monospace;
            font-size: 13.5px;
            line-height: 1.5;
            margin: 16px 0;
        }

        .mermaid-diagram {
            display: flex;
            justify-content: center;
            align-items: center;
            margin: 25px 0;
            width: 100%;
            page-break-inside: avoid;
            break-inside: avoid;
        }
        .mermaid-diagram svg {
            max-width: 100%;
            height: auto;
        }

        code {
            font-family: 'DejaVu Sans Mono', 'Liberation Mono', Menlo, Consolas, monospace;
            background-color: var(--bg-code);
            border: 1px solid var(--border-color);
            padding: 2px 6px;
            border-radius: 5px;
            font-size: 85%;
            direction: ltr;
            unicode-bidi: isolate;
            overflow-wrap: anywhere;
        }

        pre code {
            border: none;
            background-color: transparent !important;
            padding: 0;
            display: block;
        }

        table {
            border-collapse: collapse;
            width: 100%;
            margin: 20px 0;
            font-size: 14px;
            border-radius: 6px;
            box-shadow: 0 0 0 1px var(--border-color);
        }

        th, td {
            padding: 10px 14px;
            border: 1px solid var(--border-color);
        }

        th {
            background-color: var(--bg-code);
            font-weight: 600;
            text-align: start;
        }

        td { text-align: start; }

        tr:nth-child(even) {
            background-color: var(--table-even);
        }

        blockquote {
            margin: 16px 0;
            padding: 12px 18px;
            color: var(--text-main);
            border-inline-start: 4px solid var(--accent-color);
            background: var(--bg-code);
            border-radius: 6px;
        }
        blockquote > :last-child { margin-bottom: 0; }
        blockquote.callout-note { background-color: var(--note-bg); border-inline-start-color: var(--note-border); }
        blockquote.callout-warning { background-color: var(--warning-bg); border-inline-start-color: var(--warning-border); }
        blockquote.callout-tip { background-color: var(--tip-bg); border-inline-start-color: var(--tip-border); }
        blockquote.callout-important { background-color: var(--important-bg); border-inline-start-color: var(--important-border); }

        hr {
            height: 1px;
            background-color: var(--border-color);
            border: none;
            margin: 24px 0;
        }

        mjx-container {
            overflow-x: auto;
            overflow-y: hidden;
            max-width: 100%;
        }
        td mjx-container, th mjx-container {
            display: inline-block !important;
            margin: 0 !important;
        }

        /* ───── شکست صفحه ───── */
        thead { display: table-header-group; }
        tfoot { display: table-footer-group; }
        tr, img, .mermaid-diagram,
        blockquote[class*="callout-"],
        mjx-container[display="true"] {
            break-inside: avoid;
            page-break-inside: avoid;
        }
        h1, h2, h3, h4, h5, h6 {
            break-after: avoid;
            page-break-after: avoid;
        }

        /* ───── اندازهٔ فونت ───── */
        body.font-small { zoom: 0.9; }
        body.font-large { zoom: 1.15; }

        /* ───── حالت چاپ (کم‌مصرف: بدون رنگ پس‌زمینه) ───── */
        body.print-mode {
            --bg-code: #ffffff;
            --table-even: #ffffff;
            --border-color: #9aa0a6;
            --note-bg: #ffffff; --warning-bg: #ffffff;
            --tip-bg: #ffffff; --important-bg: #ffffff;
        }
        body.print-mode th { background-color: #eceff1; }
        body.print-mode blockquote {
            border: 1px solid #9aa0a6;
            border-inline-start: 4px solid #333333 !important;
        }

        /* PYGMENTS_INJECTION */
    </style>
    {{SCRIPTS}}
</head>
<body class="{{BODY_CLASSES}}">
{{CONTENT}}
</body>
</html>
"""

MATHJAX_SCRIPT = r"""
    <script>
        window.MathJax = {
            loader: { load: [{{CHEM_LOAD}}] },
            tex: {
                inlineMath: [['\\(', '\\)']],
                displayMath: [['\\[', '\\]']],
                packages: { '[+]': [{{CHEM_PKG}}] },
                processEscapes: true,
                processEnvironments: true
            },
            options: {
                ignoreHtmlClass: '.*|',
                processHtmlClass: 'arithmatex'
            },
            chtml: {
                scale: 0.95,
                fontURL: '/assets/mathjax/output/chtml/fonts/woff-v2'
            },
            startup: { typeset: false }
        };
    </script>
    <script id="MathJax-script" async src="/assets/mathjax/tex-chtml.js"></script>
"""

MERMAID_SCRIPT = '    <script src="/assets/mermaid/mermaid.min.js"></script>\n'

RENDER_JS = r"""
async ({ math, useMermaid }) => {
    await document.fonts.ready;

    if (useMermaid && window.mermaid) {
        mermaid.initialize({
            startOnLoad: false,
            securityLevel: 'strict',
            theme: 'default',
            fontFamily: 'Vazirmatn, sans-serif'
        });
        const nodes = Array.from(document.querySelectorAll('pre.mermaid'));
        for (let i = 0; i < nodes.length; i++) {
            const node = nodes[i];
            const candidates = [node.dataset.cleaned, node.dataset.raw];
            for (let j = 0; j < candidates.length; j++) {
                try {
                    const { svg } = await mermaid.render('mmd' + i + '_' + j, candidates[j]);
                    const holder = document.createElement('div');
                    holder.className = 'mermaid-diagram';
                    holder.innerHTML = svg;
                    node.replaceWith(holder);
                    break;
                } catch (e) {
                    /* تلاش با نسخهٔ بعدی کد */
                }
            }
        }
        document.querySelectorAll('[id^="dmmd"]').forEach((el) => el.remove());
    }

    if (math) {
        const t0 = Date.now();
        while (!(window.MathJax && window.MathJax.startup && window.MathJax.startup.promise)) {
            if (Date.now() - t0 > 20000) {
                throw new Error('MathJax script did not load');
            }
            await new Promise((r) => setTimeout(r, 50));
        }
        await window.MathJax.startup.promise;
        if (typeof window.MathJax.typesetPromise !== 'function') {
            throw new Error('MathJax started without typesetPromise');
        }
        await window.MathJax.typesetPromise();
    }

    await document.fonts.ready;
}
"""

RENDER_STATS_JS = r"""
() => {
    const errors = [];
    try {
        for (const item of MathJax.startup.document.math.toArray()) {
            const root = item.typesetRoot;
            if (root && root.querySelector && root.querySelector('mjx-merror')) {
                errors.push(String(item.math).trim().slice(0, 80));
            }
        }
    } catch (e) {
        const n = document.querySelectorAll('mjx-merror').length;
        for (let i = 0; i < n; i++) errors.push('?');
    }
    return {
        arith: document.querySelectorAll('.arithmatex').length,
        mjx: document.querySelectorAll('mjx-container').length,
        mermaid: document.querySelectorAll('.mermaid-diagram').length,
        mermaid_failed: document.querySelectorAll('pre.mermaid').length,
        dollars: (document.body.innerText.match(/\$/g) || []).length,
        math_error_count: errors.length,
        math_errors: errors.slice(0, 20),
    };
}
"""

FOOTER_URL = "http://render.invalid/footer.html"
PAGE_SIZES_MM = {"A4": (210.0, 297.0), "Letter": (215.9, 279.4)}
_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

FOOTER_OVERLAY_TEMPLATE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
@font-face {
    font-family: 'Vazirmatn';
    src: url('/assets/fonts/Vazirmatn-Variable.woff2') format('woff2');
    font-weight: 100 900;
    font-display: block;
}
@page { margin: 0; }
html, body { margin: 0; padding: 0; }
.pg {
    position: relative;
    width: {{W}}mm;
    height: {{H}}mm;
    overflow: hidden;
    break-after: page;
    page-break-after: always;
}
.pg:last-child { break-after: auto; page-break-after: auto; }
.ft {
    position: absolute;
    left: {{PAD}};
    right: {{PAD}};
    bottom: 6mm;
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    direction: rtl;
    font-family: 'Vazirmatn', 'Noto Sans Arabic', sans-serif;
    font-size: 8.5pt;
    color: #8c959f;
}
.ttl { max-width: 70%; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
</style></head><body>{{PAGES}}</body></html>
"""


def to_persian_digits(value) -> str:
    return str(value).translate(_PERSIAN_DIGITS)


def build_footer_overlay(total: int, title: str, pad: str, width_mm: float, height_mm: float) -> str:
    """یک صفحهٔ HTML با یک بلوک فوتر برای هر صفحهٔ PDF (فونت و اعداد فارسی)."""
    safe_title = html.escape(title or "")
    pages = "".join(
        f'<div class="pg"><div class="ft"><span class="ttl" dir="auto">{safe_title}</span>'
        f"<span>صفحه {to_persian_digits(i)} از {to_persian_digits(total)}</span></div></div>"
        for i in range(1, total + 1)
    )
    return (
        FOOTER_OVERLAY_TEMPLATE.replace("{{W}}", f"{width_mm:.2f}")
        .replace("{{H}}", f"{height_mm - 1:.2f}")
        .replace("{{PAD}}", pad)
        .replace("{{PAGES}}", pages)
    )


def count_pdf_pages(pdf_path: str) -> int:
    from pypdf import PdfReader

    return len(PdfReader(pdf_path).pages)


def stamp_footer(pdf_path: str, overlay_bytes: bytes) -> None:
    """صفحات overlay را روی صفحات PDF اصلی می‌نشاند (فهرست bookmark ها حفظ می‌شود)."""
    from pypdf import PdfReader, PdfWriter

    base = PdfReader(pdf_path)
    overlay = PdfReader(io.BytesIO(overlay_bytes))
    writer = PdfWriter(clone_from=base)
    for index in range(min(len(writer.pages), len(overlay.pages))):
        writer.pages[index].merge_page(overlay.pages[index])
    tmp_path = pdf_path + ".stamp.tmp"
    with open(tmp_path, "wb") as fh:
        writer.write(fh)
    os.replace(tmp_path, pdf_path)


async def add_footer(context, documents, pdf_path, title, page_format, orientation, pad):
    """فوتر فارسی؛ اگر هر مرحله خطا بدهد PDF بدون فوتر همان‌طور می‌ماند."""
    try:
        size = PAGE_SIZES_MM.get(page_format)
        if size is None:
            logger.warning("Footer skipped: unknown page format %s", page_format)
            return
        width_mm, height_mm = size
        if orientation == "landscape":
            width_mm, height_mm = height_mm, width_mm

        total = await asyncio.to_thread(count_pdf_pages, pdf_path)
        if total < 1:
            return
        documents[FOOTER_URL] = build_footer_overlay(total, title, pad, width_mm, height_mm)

        footer_page = await context.new_page()
        footer_page.set_default_timeout(RENDER_TIMEOUT_MS)
        await footer_page.goto(FOOTER_URL, wait_until="load")
        await footer_page.evaluate("document.fonts.ready.then(() => true)")
        overlay_bytes = await footer_page.pdf(
            format=page_format,
            landscape=(orientation == "landscape"),
            print_background=False,
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
        )
        await footer_page.close()
        await asyncio.to_thread(stamp_footer, pdf_path, overlay_bytes)
    except Exception:
        logger.exception("Footer stamping failed; keeping PDF without footer")


def render_warnings(stats, title=None) -> str:
    """پیام هشدار دربارهٔ فرمول‌های خراب و نمودارهای رندرنشده (در صورت وجود)."""
    if not stats:
        return ""
    prefix = f"{title}: " if title else ""
    parts = []
    count = stats.get("math_error_count", 0)
    if count:
        sample = "\n".join(f"• {e}" for e in stats.get("math_errors", [])[:5])
        parts.append(f"⚠️ {prefix}{count} فرمول خطا دارد و در PDF قرمز نمایش داده شده:\n{sample}")
    failed = stats.get("mermaid_failed", 0)
    if failed:
        parts.append(f"⚠️ {prefix}{failed} نمودار mermaid رندر نشد و به‌صورت متن ماند.")
    return "\n\n".join(parts)[:3500]


# ───────────────────────────── پردازش Markdown ─────────────────────────────

def auto_repair_latex(md_text: str) -> str:
    """ترمیم خودکار بک‌اسلش‌های خراب‌شده بدون استفاده از Look-behind برای سازگاری کامل با پایتون"""
    # 1. بازیابی Form Feed (\x0c) به دستور کسر \frac
    md_text = re.sub(r'[\x0c]rac\b', r'\\frac', md_text)

    # 2. بازیابی کاراکترهای Tab (\t) تبدیل‌شده به دستورات متنی و نمادهای ریاضی
    md_text = re.sub(r'\text\b', r'\\text', md_text)
    md_text = re.sub(r'\times\b', r'\\times', md_text)
    md_text = re.sub(r'\theta\b', r'\\theta', md_text)

    # 3. بازیابی فلش \rightarrow
    md_text = re.sub(r'([\r\n\x0d\s])ightarrow\b', r'\1\\rightarrow ', md_text)

    # 4. بازیابی دستور تقریب \approx
    md_text = re.sub(r'([\x07\s])pprox\b', r'\1\\approx ', md_text)

    # 5. بازیابی دستور شروع ماتریس \begin
    md_text = re.sub(r'([\x08\s]|^)egin\b', r'\1\\begin', md_text)

    # 6. بازیابی نماد چگالی \rho به جای ho
    md_text = re.sub(r'([$([{\s])ho([$)\],:\s])', r'\1\\rho\2', md_text)

    # 7. ترمیم اسلش تکی سطر ماتریس به دو اسلش
    md_text = re.sub(r'(\d)\s*\\\s*(\d)', r'\1 \\\\ \2', md_text)

    # 8. «\=» غلط است و در MathJax به‌جای مساوی، نشانهٔ بالاخط می‌سازد
    md_text = re.sub(r'\\=', '=', md_text)

    return md_text


_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_DOLLAR_PAIR_RE = re.compile(r"\$\$(.+?)\$\$")
_TRAILING_PAIR_RE = re.compile(r"^((?:(?!\$\$).)*\S)\s*\$\$(.+?)\$\$\s*$")
_LIST_ITEM_RE = re.compile(r"^\s*([-*+]|\d+[.)])\s")


def normalize_display_math(md_text: str) -> str:
    """
    فرمول‌های $$...$$ را به بلوک استاندارد تبدیل می‌کند (خط خالی قبل و بعد).
    اگر $$ چسبیده به خطوط دیگر باشد، پایتون-مارک‌داون آن را درون‌خطی می‌بیند و
    یک $ اضافه دور فرمول باقی می‌ماند.
      • $$...$$ تک‌خطی و مستقل  → بلوک
      • $$...$$ وسط متن یا داخل جدول → $\\displaystyle ...$ (درون‌خطی)
      • $$ $...$ $$ (دلار تو در تو) → دلارهای داخلی حذف می‌شود
    محتوای code block ها دست‌نخورده می‌ماند.
    """
    lines = md_text.split("\n")
    out = []
    in_fence = False
    in_math = False
    buf = []
    indent = ""

    def clean_inner(text):
        text = text.strip()
        if len(text) > 1 and text.startswith("$") and text.endswith("$"):
            text = text.strip("$").strip()
        return text

    def emit_block(content, ind):
        content = clean_inner(content)
        if not content:
            return
        if out and out[-1].strip():
            out.append("")
        out.append(f"{ind}$$")
        out.extend(f"{ind}{ln}" for ln in content.split("\n"))
        out.append(f"{ind}$$")
        out.append("")

    def inline_repl(m):
        inner = clean_inner(m.group(1))
        return f"$\\displaystyle {inner}$" if inner else ""

    for line in lines:
        if in_math:
            if "$$" in line:
                before, _, after = line.partition("$$")
                buf.append(before)
                emit_block("\n".join(buf), indent)
                in_math, buf = False, []
                if after.strip():
                    out.append(after)
            else:
                buf.append(line)
            continue

        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence or "$$" not in line:
            out.append(line)
            continue

        stripped = line.strip()
        if stripped.startswith("|"):  # ردیف جدول
            out.append(_DOLLAR_PAIR_RE.sub(inline_repl, line))
            continue

        whole = _DOLLAR_PAIR_RE.fullmatch(stripped)
        if whole:
            emit_block(whole.group(1), line[: len(line) - len(line.lstrip())])
            continue

        tail = _TRAILING_PAIR_RE.match(line)
        if tail and not _LIST_ITEM_RE.match(line):
            out.append(tail.group(1))
            emit_block(tail.group(2), line[: len(line) - len(line.lstrip())])
            continue

        replaced = _DOLLAR_PAIR_RE.sub(inline_repl, line)
        if "$$" not in replaced:
            out.append(replaced)
            continue

        # $$ بازشده که در همین خط بسته نشده → بلوک چندخطی
        before, _, after = line.partition("$$")
        if before.strip():
            out.append(before)
        indent = line[: len(line) - len(line.lstrip())]
        in_math, buf = True, [after]

    if in_math:  # بلوک بسته‌نشده؛ بدون تغییر برگردان
        out.append("$$")
        out.extend(buf)
    return "\n".join(out)


_ESC_DISPLAY_RE = re.compile(r"\\\$\\\$(.+?)\\\$\\\$")
_ESC_INLINE_RE = re.compile(r"\\\$(?!\s)((?:(?!\\\$).)+?)(?<!\s)\\\$")
_MD_UNESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!$=|<>~&:])")


def unescape_escaped_math(md_text: str) -> str:
    r"""
    بعضی ابزارها هنگام ذخیرهٔ .md همهٔ کاراکترهای خاص را escape می‌کنند:
        \$\$INR \= \\left(\\frac{a}{b}\\right)\$\$   ← فرمول با \$ شروع و تمام می‌شود
    در این حالت MathJax هیچ فرمولی نمی‌بیند. این تابع فقط فرمول‌هایی را که
    با \$ محصور شده‌اند به شکل عادی برمی‌گرداند ($...$ و $$...$$) و داخل آن‌ها
    escape ها را برمی‌دارد (\\ ← \ ،‏ \_ ← _ ،‏ \= ← =). code block ها دست‌نخورده می‌مانند.
    """
    if "\\$" not in md_text:
        return md_text

    def unesc(text):
        return _MD_UNESCAPE_RE.sub(r"\1", text)

    out = []
    in_fence = False
    for line in md_text.split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence or "\\$" not in line:
            out.append(line)
            continue
        line = _ESC_DISPLAY_RE.sub(lambda m: "$$" + unesc(m.group(1)) + "$$", line)
        line = _ESC_INLINE_RE.sub(lambda m: "$" + unesc(m.group(1)) + "$", line)
        out.append(line)
    return "\n".join(out)


CALLOUT_LABELS = {
    "NOTE": ("note", "📌 نکته:"),
    "WARNING": ("warning", "⚠️ هشدار:"),
    "TIP": ("tip", "💡 پیشنهاد:"),
    "IMPORTANT": ("important", "🔥 مهم:"),
}
CALLOUT_ALERT_RE = re.compile(
    r"<blockquote>\s*<p>\s*\[!(NOTE|WARNING|TIP|IMPORTANT)\]\s*(?:<br\s*/?>)?\s*",
    re.IGNORECASE,
)
CALLOUT_EMOJI_RE = re.compile(
    r"<blockquote>\s*<p>\s*(?:<strong>)?\s*(📌|⚠\ufe0f?|💡|🔥)"
)
EMOJI_CALLOUT_CLASS = {"📌": "note", "⚠": "warning", "💡": "tip", "🔥": "important"}


def apply_callouts(html_text: str) -> str:
    """تبدیل blockquote های `> [!NOTE]` و blockquote هایی که با ⚠️ 💡 📌 🔥 شروع می‌شوند به callout رنگی."""

    def alert_repl(match):
        css, label = CALLOUT_LABELS[match.group(1).upper()]
        return f'<blockquote class="callout-{css}"><p><strong>{label}</strong> '

    def emoji_repl(match):
        css = EMOJI_CALLOUT_CLASS[match.group(1).rstrip("\ufe0f")]
        return match.group(0).replace("<blockquote>", f'<blockquote class="callout-{css}">', 1)

    html_text = CALLOUT_ALERT_RE.sub(alert_repl, html_text)
    return CALLOUT_EMOJI_RE.sub(emoji_repl, html_text)


def clean_mermaid_script(code: str) -> str:
    lines = code.strip().splitlines()
    cleaned_lines = []
    sg_idx = 0
    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue

        sg_match = re.match(r'^subgraph\s+(.+)$', line_str, re.IGNORECASE)
        if sg_match:
            title = sg_match.group(1).strip()
            if not (title.startswith('"') and title.endswith('"')) and not ('[' in title and ']' in title):
                sg_idx += 1
                cleaned_lines.append(f'subgraph sg_{sg_idx} ["{title}"]')
                continue

        def quote_bracket(m):
            inner = m.group(1).strip()
            if (inner.startswith('"') and inner.endswith('"')) or (inner.startswith("'") and inner.endswith("'")):
                return f'[{inner}]'
            escaped = inner.replace('"', "'")
            return f'["{escaped}"]'

        line_str = re.sub(r'\[([^\[\]]+)\]', quote_bracket, line_str)
        cleaned_lines.append(line_str)

    return "\n".join(cleaned_lines)


MERMAID_FENCE_RE = re.compile(
    r"```(?:mermaid|flowchart)[^\n\r]*\r?\n([\s\S]*?)```", re.IGNORECASE
)

ALLOWED_TAGS = {
    "a", "abbr", "b", "blockquote", "br", "code", "dd", "del", "details", "div",
    "dl", "dt", "em", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img", "ins",
    "kbd", "li", "mark", "ol", "p", "pre", "s", "small", "span", "strong", "sub",
    "summary", "sup", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "u", "ul",
}
ALLOWED_ATTRS = {
    "*": {"class", "id", "lang", "title"},
    "a": {"href"},
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan", "align"},
    "th": {"colspan", "rowspan", "align"},
    "ol": {"start"},
    "details": {"open"},
}
ALLOWED_URL_SCHEMES = {"http", "https", "mailto", "data"}
DIR_AUTO_RE = re.compile(r"<(p|h[1-6]|ul|ol|li|table|blockquote|dl)(?=[\s>])")


def build_html(md_text, orientation="portrait", compact=False, columns=1, font_size="normal", print_mode=False):
    """Markdown → HTML کامل. خروجی: (html, has_math, has_mermaid)"""
    # نمودارهای mermaid قبل از هر پردازش دیگری جدا می‌شوند و بعد از پاک‌سازی HTML برمی‌گردند
    token = "MMD" + secrets.token_hex(8) + "X"
    mermaid_blocks = []

    def stash_mermaid(match):
        mermaid_blocks.append(match.group(1).strip())
        return f"\n\n{token}{len(mermaid_blocks) - 1}END\n\n"

    md_text = MERMAID_FENCE_RE.sub(stash_mermaid, md_text)
    md_text = unescape_escaped_math(md_text)
    md_text = normalize_display_math(md_text)
    md_text = auto_repair_latex(md_text)

    body = markdown.markdown(
        md_text,
        extensions=["fenced_code", "codehilite", "tables", "nl2br", "toc", "pymdownx.arithmatex"],
        extension_configs={
            "codehilite": {"guess_lang": False, "css_class": "codehilite"},
            "pymdownx.arithmatex": {"generic": True},
        },
    )
    body = apply_callouts(body)

    # HTML خام کاربر (اسکریپت، iframe، ...) حذف می‌شود
    body = nh3.clean(
        body,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        url_schemes=ALLOWED_URL_SCHEMES,
    )
    has_math = 'class="arithmatex"' in body

    # جهت هر بلوک (راست‌به‌چپ / چپ‌به‌راست) جداگانه از روی اولین حرف قوی تعیین می‌شود
    body = DIR_AUTO_RE.sub(r'<\1 dir="auto"', body)

    for idx, code in enumerate(mermaid_blocks):
        pre = (
            '<pre class="mermaid" '
            f'data-cleaned="{html.escape(clean_mermaid_script(code), quote=True)}" '
            f'data-raw="{html.escape(code, quote=True)}">'
            f"{html.escape(code)}</pre>"
        )
        placeholder = f"{token}{idx}END"
        body, n = re.subn(
            rf"<p[^>]*>\s*{re.escape(placeholder)}\s*</p>", lambda _m: pre, body
        )
        if n == 0:
            body = body.replace(placeholder, pre)

    classes = []
    if compact:
        classes.append("compact-mode")
    if orientation == "landscape":
        classes.append("landscape-mode")
    if columns == 2:
        classes.append("columns-2")
    if font_size in ("small", "large"):
        classes.append(f"font-{font_size}")
    if print_mode:
        classes.append("print-mode")

    scripts = ""
    if has_math:
        chem = "\\ce{" in body or "\\pu{" in body
        scripts += MATHJAX_SCRIPT.replace(
            "{{CHEM_LOAD}}", "'[tex]/mhchem'" if chem else ""
        ).replace("{{CHEM_PKG}}", "'mhchem'" if chem else "")
    if mermaid_blocks:
        scripts += MERMAID_SCRIPT

    # محتوا آخر از همه جایگذاری می‌شود تا متن کاربر هرگز با placeholder ها اشتباه گرفته نشود
    full_html = (
        HTML_TEMPLATE.replace("/* PYGMENTS_INJECTION */", CODE_STYLE_LIGHT)
        .replace("{{SCRIPTS}}", scripts)
        .replace("{{BODY_CLASSES}}", " ".join(classes))
        .replace("{{CONTENT}}", body)
    )
    return full_html, has_math, bool(mermaid_blocks)


def error_detail(exc) -> str:
    if not DEBUG_ERRORS:
        return ""
    return f"\n\nجزئیات: {type(exc).__name__}: {str(exc)[:300]}"


def clean_filename(text):
    text = re.sub(r'[\\/*?:"<>|#\x00-\x1f]', "", text or "").strip()
    return text[:40].strip()


def decode_text(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1256", errors="replace")


# ───────────────────────────── مرورگر و تولید PDF ─────────────────────────────

async def ensure_browser():
    """مرورگر را می‌سازد؛ اگر کرش کرده باشد دوباره راه‌اندازی می‌کند."""
    global global_browser, playwright_instance
    async with browser_lock:
        if global_browser is not None and global_browser.is_connected():
            return global_browser
        if global_browser is not None:
            with contextlib.suppress(Exception):
                await global_browser.close()
            global_browser = None
        if playwright_instance is None:
            playwright_instance = await async_playwright().start()
        global_browser = await playwright_instance.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                f"--js-flags=--max-old-space-size={JS_HEAP_MB}",
            ],
        )
        logger.info("Browser instance initialized.")
        return global_browser


async def close_browser():
    global global_browser, playwright_instance
    with contextlib.suppress(Exception):
        if global_browser is not None:
            await global_browser.close()
    with contextlib.suppress(Exception):
        if playwright_instance is not None:
            await playwright_instance.stop()
    global_browser = None
    playwright_instance = None


_ASSET_MIME = {
    ".js": "text/javascript",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
}


def make_router(documents: dict):
    """فقط سند و فایل‌های محلی assets مجازند؛ بقیهٔ درخواست‌ها (از جمله file://) بسته می‌شوند."""
    assets_root = ASSETS_DIR.resolve()

    async def router(route):
        request = route.request
        url = request.url
        try:
            if url in documents:
                await route.fulfill(
                    status=200, content_type="text/html; charset=utf-8", body=documents[url]
                )
                return
            if url.startswith(ASSET_PREFIX):
                rel = unquote(urlparse(url).path[len("/assets/"):])
                target = (assets_root / rel).resolve()
                if assets_root in target.parents and target.is_file():
                    mime = _ASSET_MIME.get(target.suffix.lower())
                    if mime:
                        await route.fulfill(path=str(target), content_type=mime)
                    else:
                        await route.fulfill(path=str(target))
                    return
            elif (
                ALLOW_REMOTE_IMAGES
                and request.resource_type == "image"
                and url.startswith(("http://", "https://"))
            ):
                await route.continue_()
                return
        except Exception:
            logger.debug("route handler error for %s", url, exc_info=True)
        with contextlib.suppress(Exception):
            await route.abort()

    return router


async def generate_pdf_output(
    md_text,
    output_pdf_path,
    orientation="portrait",
    compact=False,
    columns=1,
    page_format=None,
    font_size="normal",
    print_mode=False,
    title="",
):
    full_html, has_math, has_mermaid = await asyncio.to_thread(
        build_html, md_text, orientation, compact, columns, font_size, print_mode
    )

    browser = await ensure_browser()
    context = await browser.new_context(service_workers="block")
    try:
        documents = {DOC_URL: full_html}
        await context.route("**/*", make_router(documents))
        page = await context.new_page()
        page.set_default_timeout(RENDER_TIMEOUT_MS)
        await page.goto(DOC_URL, wait_until="load")
        await page.evaluate(RENDER_JS, {"math": has_math, "useMermaid": has_mermaid})
        stats = await page.evaluate(RENDER_STATS_JS)
        logger.info("render stats: %s (version %s)", stats, BOT_VERSION)
        if has_math and stats.get("arith", 0) > 0 and stats.get("mjx", 0) == 0:
            raise RuntimeError("MathJax did not render any formula")

        page_margin = "12mm" if compact else "20mm"
        page_format = page_format or PDF_PAGE_FORMAT
        await page.pdf(
            path=output_pdf_path,
            format=page_format,
            landscape=(orientation == "landscape"),
            print_background=True,
            outline=True,
            tagged=True,
            margin={
                "top": page_margin,
                "bottom": page_margin,
                "left": page_margin,
                "right": page_margin,
            },
        )
        await add_footer(
            context, documents, output_pdf_path, title, page_format, orientation, page_margin
        )
    finally:
        with contextlib.suppress(Exception):
            await context.close()
        gc.collect()
    return stats


async def run_conversion(md_text, pdf_path, settings):
    async with conversion_semaphore:
        return await asyncio.wait_for(
            generate_pdf_output(md_text, pdf_path, **settings),
            timeout=CONVERSION_TIMEOUT,
        )


# ───────────────────────────── ابزارهای تلگرام ─────────────────────────────

@contextlib.contextmanager
def user_job(user_id):
    """هر کاربر در هر لحظه فقط یک کار فعال دارد (جلوگیری از پر کردن صف)."""
    if user_id in _active_users:
        yield False
        return
    _active_users.add(user_id)
    try:
        yield True
    finally:
        _active_users.discard(user_id)


async def check_access(update: Update) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    user = update.effective_user
    if user and user.id in ALLOWED_USER_IDS:
        return True
    if update.callback_query:
        await update.callback_query.answer("⛔ دسترسی ندارید", show_alert=True)
    elif update.message:
        await update.message.reply_text("⛔ شما اجازهٔ استفاده از این ربات را ندارید.")
    return False


async def safe_edit(message, text):
    try:
        await message.edit_text(text)
    except Exception:
        logger.debug("edit_text failed", exc_info=True)


async def safe_delete(message):
    try:
        await message.delete()
    except Exception:
        logger.debug("delete failed", exc_info=True)


async def send_pdf(message, pdf_path, filename):
    if os.path.getsize(pdf_path) > TELEGRAM_UPLOAD_LIMIT:
        raise ValueError("PDF بزرگ‌تر از حد مجاز ارسال تلگرام است")
    with open(pdf_path, "rb") as pdf_file:
        await message.reply_document(document=pdf_file, filename=filename, write_timeout=120)


def get_settings_keyboard(chat_id):
    orientation = get_user_setting(chat_id, "orientation", "portrait")
    compact = get_user_setting(chat_id, "compact", False)
    columns = get_user_setting(chat_id, "columns", 1)

    orient_btn = "📑 جهت: افقی" if orientation == "landscape" else "📄 جهت: عمودی"
    compact_btn = "📦 حالت: فشرده" if compact else "📖 حالت: عادی"
    col_btn = "📰 ستون: دو ستونی" if columns == 2 else "📃 ستون: تک ستونی"
    page_format = get_user_setting(chat_id, "page_format", PDF_PAGE_FORMAT)
    font_size = get_user_setting(chat_id, "font_size", "normal")
    print_mode = get_user_setting(chat_id, "print_mode", False)

    page_btn = f"📏 اندازه: {page_format}"
    font_btn = {
        "small": "🔡 فونت: کوچک",
        "normal": "🔤 فونت: معمولی",
        "large": "🔠 فونت: بزرگ",
    }.get(font_size, "🔤 فونت: معمولی")
    print_btn = "🖨 چاپ: کم‌مصرف" if print_mode else "🎨 چاپ: رنگی"

    keyboard = [
        [
            InlineKeyboardButton(orient_btn, callback_data="toggle_orient"),
            InlineKeyboardButton(compact_btn, callback_data="toggle_compact"),
        ],
        [InlineKeyboardButton(col_btn, callback_data="toggle_cols")],
        [
            InlineKeyboardButton(page_btn, callback_data="toggle_page"),
            InlineKeyboardButton(font_btn, callback_data="cycle_font"),
        ],
        [InlineKeyboardButton(print_btn, callback_data="toggle_print")],
    ]
    return InlineKeyboardMarkup(keyboard)


MENU_TEXT = (
    "سلام! 👋\n\n"
    "📄 فایل .md/.txt، متن دلخواه و یا فایل فشرده .zip خود را بفرستید.\n"
    "💡 نکته: نام فایل خروجی PDF دقیقا مطابق با نام فایل اصلی شما تنظیم می‌شود.\n\n"
    "⚙️ تنظیمات خروجی خود را از طریق دکمه‌های زیر مدیریت کنید:\n\n"
    f"🔖 نسخه: {BOT_VERSION}"
)


async def show_menu(update: Update):
    chat_id = update.effective_chat.id
    reply_markup = get_settings_keyboard(chat_id)
    if update.callback_query:
        try:
            await update.callback_query.message.edit_text(MENU_TEXT, reply_markup=reply_markup)
        except BadRequest:
            pass  # «Message is not modified»
    elif update.message:
        await update.message.reply_text(MENU_TEXT, reply_markup=reply_markup)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update):
        return
    await show_menu(update)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await check_access(update):
        return
    await query.answer()
    chat_id = update.effective_chat.id

    data = query.data
    if data == "toggle_orient":
        current = get_user_setting(chat_id, "orientation", "portrait")
        set_user_setting(chat_id, "orientation", "landscape" if current == "portrait" else "portrait")
    elif data == "toggle_compact":
        current = get_user_setting(chat_id, "compact", False)
        set_user_setting(chat_id, "compact", not current)
    elif data == "toggle_cols":
        current = get_user_setting(chat_id, "columns", 1)
        set_user_setting(chat_id, "columns", 2 if current == 1 else 1)
    elif data == "toggle_page":
        current = get_user_setting(chat_id, "page_format", PDF_PAGE_FORMAT)
        set_user_setting(chat_id, "page_format", "Letter" if current == "A4" else "A4")
    elif data == "cycle_font":
        current = get_user_setting(chat_id, "font_size", "normal")
        index = FONT_SIZES.index(current) if current in FONT_SIZES else 1
        set_user_setting(chat_id, "font_size", FONT_SIZES[(index + 1) % len(FONT_SIZES)])
    elif data == "toggle_print":
        current = get_user_setting(chat_id, "print_mode", False)
        set_user_setting(chat_id, "print_mode", not current)

    await show_menu(update)


async def process_conversion(update: Update, context: ContextTypes.DEFAULT_TYPE, md_text: str, file_default_name=None):
    message = update.message
    chat_id = update.effective_chat.id
    file_title = clean_filename(file_default_name) or f"Note_{message.message_id}"
    settings = {**get_conversion_settings(chat_id), "title": file_title}

    status_msg = await message.reply_text(f"⏳ در حال تبدیل {file_title}.pdf ...")

    with tempfile.TemporaryDirectory(prefix="md2pdf_") as tmpdir:
        pdf_path = os.path.join(tmpdir, "out.pdf")
        try:
            stats = await run_conversion(md_text, pdf_path, settings)
            await send_pdf(message, pdf_path, f"{file_title}.pdf")
            await safe_delete(status_msg)
            warning = render_warnings(stats)
            if warning:
                try:
                    await message.reply_text(warning)
                except Exception:
                    logger.debug("warning message failed", exc_info=True)
        except asyncio.TimeoutError:
            logger.warning("Conversion timed out for %s", file_title)
            await safe_edit(status_msg, f"❌ تبدیل {file_title} بیش از حد طول کشید و لغو شد.")
        except Exception as exc:
            logger.exception("Conversion failed for %s", file_title)
            await safe_edit(
                status_msg,
                f"❌ خطا در تبدیل {file_title}. لطفاً محتوای فایل را بررسی و دوباره تلاش کنید."
                + error_detail(exc),
            )


def read_zip_documents(zip_path):
    """فایل‌های متنی داخل ZIP را مستقیماً در حافظه و با محدودیت حجم می‌خواند (بدون extractall)."""
    docs, skipped = [], []
    total = 0
    used_titles = {}

    with zipfile.ZipFile(zip_path) as zf:
        infos = sorted((i for i in zf.infolist() if not i.is_dir()), key=lambda i: i.filename)
        for info in infos:
            name = info.filename
            base = os.path.basename(name)
            if name.startswith("__MACOSX/") or base.startswith("._") or not base:
                continue
            if not base.lower().endswith(TEXT_EXTENSIONS):
                continue
            if len(docs) >= MAX_ZIP_ENTRIES:
                skipped.append(f"{base} (بیش از سقف {MAX_ZIP_ENTRIES} فایل)")
                continue
            try:
                with zf.open(info) as fh:
                    data = fh.read(MAX_TEXT_BYTES + 1)
            except Exception:
                skipped.append(f"{base} (قابل خواندن نیست)")
                continue
            if len(data) > MAX_TEXT_BYTES:
                skipped.append(f"{base} (حجم زیاد)")
                continue
            total += len(data)
            if total > MAX_ZIP_UNCOMPRESSED:
                skipped.append(f"{base} (سقف حجم کل ZIP)")
                break

            title = clean_filename(os.path.splitext(base)[0]) or "Note"
            count = used_titles.get(title, 0)
            used_titles[title] = count + 1
            if count:
                title = f"{title}_{count + 1}"
            docs.append((title, decode_text(data)))
    return docs, skipped


async def handle_zip(update: Update, context: ContextTypes.DEFAULT_TYPE, zip_path: str, tmpdir: str):
    message = update.message
    chat_id = update.effective_chat.id
    settings = get_conversion_settings(chat_id)

    status_msg = await message.reply_text("📦 در حال خواندن فایل ZIP ...")
    try:
        docs, skipped = await asyncio.to_thread(read_zip_documents, zip_path)
    except zipfile.BadZipFile:
        await safe_edit(status_msg, "❌ فایل ZIP معتبر نیست.")
        return
    except Exception:
        logger.exception("ZIP read failed")
        await safe_edit(status_msg, "❌ خطا در پردازش فایل ZIP.")
        return

    if not docs:
        await safe_edit(status_msg, "❌ هیچ فایل .md یا .txt معتبری داخل فایل ZIP یافت نشد.")
        return

    failed = []
    warnings = []
    for idx, (title, text) in enumerate(docs, 1):
        await safe_edit(status_msg, f"⏳ ({idx}/{len(docs)}) در حال تبدیل {title}.pdf ...")
        pdf_path = os.path.join(tmpdir, f"zip_{idx}.pdf")
        try:
            stats = await run_conversion(text, pdf_path, {**settings, "title": title})
            await send_pdf(message, pdf_path, f"{title}.pdf")
            warning = render_warnings(stats, title)
            if warning:
                warnings.append(warning)
        except asyncio.TimeoutError:
            logger.warning("Conversion timed out for %s", title)
            failed.append(f"{title} (زمان تبدیل تمام شد)")
        except Exception as exc:
            logger.exception("Conversion failed for %s", title)
            failed.append(title + error_detail(exc))
        finally:
            with contextlib.suppress(OSError):
                os.remove(pdf_path)

    await safe_delete(status_msg)

    if failed or skipped or warnings:
        lines = []
        if warnings:
            lines.append("\n\n".join(warnings[:5]))
        if failed:
            lines.append("❌ تبدیل این فایل‌ها ناموفق بود:\n" + "\n".join(f"• {n}" for n in failed[:10]))
        if skipped:
            lines.append("⚠️ این فایل‌ها نادیده گرفته شدند:\n" + "\n".join(f"• {n}" for n in skipped[:10]))
        await message.reply_text("\n\n".join(lines)[:4000])


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.document:
        return
    if not await check_access(update):
        return

    doc = update.message.document
    filename = doc.file_name or ""
    lower = filename.lower()
    mime = (doc.mime_type or "").lower()

    if lower.endswith(TEXT_EXTENSIONS):
        kind = "text"
    elif lower.endswith(".zip"):
        kind = "zip"
    elif not lower and mime in ("text/markdown", "text/x-markdown", "text/plain"):
        kind = "text"
    elif not lower and mime in ("application/zip", "application/x-zip-compressed"):
        kind = "zip"
    else:
        await update.message.reply_text("⛔ لطفاً فقط فایل .md، .txt یا .zip بفرستید.")
        return

    limit = MAX_ZIP_BYTES if kind == "zip" else MAX_TEXT_BYTES
    if doc.file_size and doc.file_size > limit:
        await update.message.reply_text(
            f"⛔ حجم فایل بیش از حد مجاز است (حداکثر {limit // (1024 * 1024)} مگابایت)."
        )
        return

    user_id = update.effective_user.id if update.effective_user else update.effective_chat.id
    with user_job(user_id) as acquired:
        if not acquired:
            await update.message.reply_text("⏳ درخواست قبلی شما هنوز در حال پردازش است. لطفاً کمی صبر کنید.")
            return

        with tempfile.TemporaryDirectory(prefix="md2pdf_dl_") as tmpdir:
            local_path = os.path.join(tmpdir, "upload.bin")
            try:
                tg_file = await context.bot.get_file(doc.file_id)
                await tg_file.download_to_drive(local_path)
            except Exception:
                logger.exception("Download failed")
                await update.message.reply_text("❌ دانلود فایل از تلگرام ناموفق بود.")
                return

            if kind == "zip":
                await handle_zip(update, context, local_path, tmpdir)
            else:
                with open(local_path, "rb") as f:
                    data = f.read(MAX_TEXT_BYTES + 1)
                if len(data) > MAX_TEXT_BYTES:
                    await update.message.reply_text("⛔ حجم فایل بیش از حد مجاز است.")
                    return
                base_name = os.path.splitext(filename)[0] if filename else ""
                await process_conversion(update, context, decode_text(data), file_default_name=base_name)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    if not await check_access(update):
        return
    text = update.message.text
    if text.startswith("/"):
        return

    user_id = update.effective_user.id if update.effective_user else update.effective_chat.id
    with user_job(user_id) as acquired:
        if not acquired:
            await update.message.reply_text("⏳ درخواست قبلی شما هنوز در حال پردازش است. لطفاً کمی صبر کنید.")
            return
        await process_conversion(update, context, text)


SELFTEST_MD = r"""فرمول محاسبه: $$INR = \left(\frac{\text{PT}_{\text{Patient}}}{\text{MNPT}}\right)^{ISI}$$

- $\text{MNPT}$: آزمون
- $ISI$: آزمون
"""


async def selftest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رندر یک نمونهٔ ثابت و گزارش وضعیت؛ برای عیب‌یابی."""
    if not update.message or not await check_access(update):
        return
    checks = {
        "mathjax": (ASSETS_DIR / "mathjax" / "tex-chtml.js").is_file(),
        "mermaid": (ASSETS_DIR / "mermaid" / "mermaid.min.js").is_file(),
        "font": (ASSETS_DIR / "fonts" / "Vazirmatn-Variable.woff2").is_file(),
    }
    status = await update.message.reply_text("🧪 در حال آزمایش ...")
    with tempfile.TemporaryDirectory(prefix="md2pdf_self_") as tmpdir:
        pdf_path = os.path.join(tmpdir, "selftest.pdf")
        try:
            stats = await run_conversion(SELFTEST_MD, pdf_path, get_conversion_settings(update.effective_chat.id))
            report = f"✅ نسخه {BOT_VERSION}\nفایل‌ها: {checks}\nآمار رندر: {stats}"
            await send_pdf(update.message, pdf_path, "selftest.pdf")
        except Exception as exc:
            logger.exception("Selftest failed")
            report = f"❌ نسخه {BOT_VERSION}\nفایل‌ها: {checks}\nخطا: {type(exc).__name__}: {str(exc)[:400]}"
    await safe_delete(status)
    await update.message.reply_text(report)


async def error_handler(update, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled error while processing an update", exc_info=context.error)


async def post_init(application: Application):
    try:
        await ensure_browser()
    except Exception:
        logger.exception("Browser warm-up failed; it will be retried on the first request")


async def post_shutdown(application: Application):
    await close_browser()


def main():
    if "--fetch-assets" in sys.argv:
        ensure_assets(force=True)
        return

    token = os.environ.get("BOT_TOKEN")
    if not token:
        logger.error("BOT_TOKEN is missing!")
        sys.exit(1)

    threading.Thread(target=run_dummy_server, daemon=True).start()
    ensure_assets()

    logger.info("Starting Telegram Bot... version=%s", BOT_VERSION)
    app = (
        Application.builder()
        .token(token)
        .concurrent_updates(True)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler(["start", "help", "settings"], start))
    app.add_handler(CommandHandler("selftest", selftest))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)

    app.run_polling()


if __name__ == "__main__":
    main()
