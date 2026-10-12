"""md2pdf.selftest"""
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from collections import Counter
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
import asyncio
import converters
import os
import re
import shutil
import subprocess
import tempfile
import time
from md2pdf.config import (ASSETS_DIR, BOT_VERSION, logger)
from md2pdf.handlers import (check_access, safe_delete, send_pdf)
from md2pdf.html_build import (apply_latin_spans, build_html)
from md2pdf.pdf_layout import (_letters)
from md2pdf.pdf_render import (ensure_browser, run_conversion)
from md2pdf.settings_store import (get_conversion_settings)




SELFTEST_MD = r"""# عنوان آزمایشی

# فصل اول آزمایشی

## فاز I و فاز II (Functionalization Reactions)

متن فارسی با Drug Metabolism داخل پرانتز (CYP3A4) و فاز I و فاز II.

> [!NOTE]
> نکتهٔ آزمایشی

> [!EXAMPLE]
> مثال بالینی آزمایشی

> [!CLINICAL]
> نکتهٔ بالینی آزمایشی

> [!REVIEW]
> سؤال مرور آزمایشی

| مشخصه | فاز I (Phase) |
|---|---|
| هدف اصلی | اکسپوز |

```python
x = 1
```

فرمول محاسبه: $$INR = \left(\frac{\text{PT}_{\text{Patient}}}{\text{MNPT}}\right)^{ISI}$$

- $\text{MNPT}$: آزمون
- $ISI$: آزمون

### خلاصه فصل

خلاصهٔ آزمایشی.

## بخش اول

متن نهایی.
"""




def _pypdf_version():
    try:
        import pypdf

        return getattr(pypdf, "__version__", "installed")
    except Exception:
        return None




CALLOUT_CLASS_RE = re.compile(r'class="(callout-\w+)"')




def _inspect_pdf(pdf_path: str, chapter_text: str) -> dict:
    """بررسی‌های خواندنی از روی PDF نهایی (صفحه‌ها، فونت‌ها، فهرست، هدر، متادیتا)."""
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    pages = list(reader.pages)
    texts = [(pg.extract_text() or "") for pg in pages]
    fonts = set()
    for pg in pages:
        try:
            resources = pg.get("/Resources") or {}
            font_dict = resources.get("/Font") or {}
            for key in font_dict:
                base = font_dict[key].get_object().get("/BaseFont")
                if base:
                    fonts.add(str(base).split("+")[-1].lstrip("/"))
        except Exception:
            continue
    chapter_key = _letters(chapter_text)
    header_pages = [i for i, t in enumerate(texts) if chapter_key and (chapter_key - _letters(t)) == Counter()]
    meta = reader.metadata or {}
    return {
        "pages": len(pages),
        "toc_dashes": texts[1].count("–") if len(texts) > 1 else None,
        "fonts": sorted(fonts),
        "header_pages": header_pages[:6],
        "author": str(meta.get("/Author", "")),
        "producer": str(meta.get("/Producer", "")),
    }




def font_files_info() -> dict:
    """حجم و نام داخلی فایل‌های فونت در assets (برای تشخیص فایل خراب)."""
    result = {}
    folder = ASSETS_DIR / "fonts"
    names = sorted(os.listdir(folder)) if folder.is_dir() else []
    for name in names:
        path = folder / name
        try:
            from fontTools.ttLib import TTFont

            font = TTFont(str(path), lazy=True)
            family = font["name"].getDebugName(1) or "?"
            result[name] = f"{path.stat().st_size} bytes, family={family}"
        except Exception as exc:
            result[name] = f"{path.stat().st_size} bytes, خطا: {type(exc).__name__}"
    return result




def _env_report(chromium_version: str) -> dict:
    def fc(name):
        try:
            out = subprocess.run(["fc-match", name], capture_output=True, text=True, timeout=5).stdout.strip()
            return out.split(":")[0] if out else "نامشخص"
        except Exception:
            return "خطا"

    try:
        converters.find_pandoc()
        pandoc = True
    except Exception:
        pandoc = False
    return {
        "fc_Vazirmatn": fc("Vazirmatn"),
        "fc_Arial": fc("Arial"),
        "chromium": chromium_version,
        "libreoffice": shutil.which("soffice") is not None,
        "pandoc": pandoc,
        "pypdf": _pypdf_version(),
        "mathjax_asset": (ASSETS_DIR / "mathjax" / "tex-chtml.js").is_file(),
        "mermaid_asset": (ASSETS_DIR / "mermaid" / "mermaid.min.js").is_file(),
        "vazir_ttf_static": (ASSETS_DIR / "fonts" / "Vazirmatn-Regular.ttf").is_file(),
        "fonts_in_assets": font_files_info(),
    }




def _latin_report() -> dict:
    sample = "متن (Drug Metabolism) و فاز I و فاز II (CYP3A4) و Abc &amp; def."
    out = apply_latin_spans(sample)
    spans = re.findall(r'<span class="en" dir="ltr">(.*?)</span>', out)
    bracket_inside = False
    space_edge = False
    for sp in spans:
        edges = [sp[:1], sp[-1:]]
        for ch in edges:
            if ch in ("(", ")"):
                bracket_inside = True
        if sp != sp.strip():
            space_edge = True
    return {
        "spans": len(spans),
        "bracket_inside_span": bracket_inside,
        "space_at_edge": space_edge,
        "entity_broken": "&amp;</span>" in out,
        "sample_out": out[:160],
    }




def _split_message(text: str, limit: int = 3500) -> list:
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            chunks.append(current)
            current = ""
        current += line + "\n"
    if current.strip():
        chunks.append(current)
    return chunks




async def selftest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رندر یک نمونهٔ ثابت و گزارش کامل وضعیت محیط، فونت‌ها، فهرست، هدر و قالب."""
    if not update.message or not await check_access(update):
        return
    chat_id = update.effective_chat.id
    settings = get_conversion_settings(chat_id)
    status = await update.message.reply_text("🧪 در حال آزمایش ...")

    try:
        browser = await ensure_browser()
        chromium_version = browser.version
    except Exception as exc:
        chromium_version = f"خطا: {type(exc).__name__}"
    env = _env_report(chromium_version)
    lines = [f"🔖 نسخه: {BOT_VERSION}", "", "🖥 محیط:"]
    lines += [f"  {k}: {v}" for k, v in env.items()]
    lines.append("")
    lines.append("🔤 فونت لاتین (Latin spans):")
    lines += [f"  {k}: {v}" for k, v in _latin_report().items()]

    chapter = "فصل اول آزمایشی"
    with tempfile.TemporaryDirectory(prefix="md2pdf_self_") as tmpdir:
        pdf_path = os.path.join(tmpdir, "selftest.pdf")
        try:
            started = time.perf_counter()
            stats = await run_conversion(
                SELFTEST_MD, pdf_path, {**settings, "title": "selftest"}
            )
            elapsed = time.perf_counter() - started
            info = await asyncio.to_thread(_inspect_pdf, pdf_path, chapter)
            lines.append("")
            lines.append("📄 نتیجهٔ رندر:")
            lines.append(f"  زمان: {elapsed:.1f} ثانیه")
            lines.append(f"  footer: {stats.get('footer')}")
            lines.append(f"  front_matter: {stats.get('front_matter')}")
            lines.append(f"  heading_diag: {stats.get('heading_diag')}")
            lines.append(f"  bookmarks: {stats.get('bookmarks')}")
            lines.append(f"  mathjax: {stats.get('arith')} فرمول، خطا: {stats.get('math_error_count')}")
            sample_html = build_html(SELFTEST_MD, front=True)[0]
            callout_classes = sorted(set(CALLOUT_CLASS_RE.findall(sample_html)))
            lines.append(f"  callouts در HTML: {callout_classes}")
            lines.append(f"  وضعیت فونت‌ها در مرورگر: {stats.get('font_faces')}")
            lines.append("")
            lines.append("🔍 بررسی PDF:")
            lines += [f"  {k}: {v}" for k, v in info.items()]
            lines.append(f"  هدر فصل «{chapter}» در صفحات: {info['header_pages']}")
            await send_pdf(update.message, pdf_path, "selftest.pdf")
        except Exception as exc:
            logger.exception("Selftest failed")
            lines.append("")
            lines.append(f"❌ خطا در رندر: {type(exc).__name__}: {str(exc)[:400]}")
    await safe_delete(status)
    for chunk in _split_message("\n".join(lines)):
        await update.message.reply_text(chunk)

