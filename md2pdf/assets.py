"""md2pdf.assets"""
from pathlib import Path
import converters
import io
import tarfile
import urllib.request
from md2pdf.config import (ASSETS_DIR, logger)




# ───────────────────── فایل‌های محلی (MathJax / Mermaid / فونت) ─────────────────────
# این فایل‌ها هنگام build با `python bot.py --fetch-assets` دانلود می‌شوند و در زمان
# رندر از روی دیسک سرو می‌شوند؛ مرورگر هیچ دسترسی اینترنتی ندارد.

ASSETS_VERSION = "4"


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
    fonts, ttfs = {}, {}
    with tarfile.open(fileobj=io.BytesIO(_download(VAZIRMATN_URL)), mode="r:gz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            if member.name.endswith(".woff2"):
                fonts[member.name] = tar.extractfile(member).read()
            elif member.name.endswith(".ttf") and "Vazirmatn" in member.name:
                ttfs[member.name] = tar.extractfile(member).read()
    pick = next((n for n in fonts if "wght" in n or "variable" in n.lower()), None)
    if pick is None:
        raise RuntimeError(f"فونت متغیر Vazirmatn پیدا نشد. فایل‌ها: {list(fonts)}")
    _safe_write(ASSETS_DIR / "fonts", "Vazirmatn-Variable.woff2", fonts[pick])

    # فونت TTF برای LibreOffice (تبدیل Word به PDF در آینده)
    ttf_pick = next((n for n in ttfs if "Variable" in n or "wght" in n), None) or next(iter(ttfs), None)
    if ttf_pick:
        _safe_write(ASSETS_DIR / "fonts", "Vazirmatn-Variable.ttf", ttfs[ttf_pick])
        try:
            static = converters.make_static_fonts(
                str(ASSETS_DIR / "fonts" / "Vazirmatn-Variable.ttf"), str(ASSETS_DIR / "fonts")
            )
            logger.info("Static Vazirmatn fonts ready: %s", sorted(static))
        except Exception:
            logger.exception("Creating static Vazirmatn fonts failed; LibreOffice will use the variable font")
    else:
        logger.warning("Vazirmatn TTF not found in package; LibreOffice will substitute fonts")

    required = [
        ASSETS_DIR / "mathjax" / "tex-chtml.js",
        ASSETS_DIR / "mathjax" / "input" / "tex" / "extensions" / "mhchem.js",
        ASSETS_DIR / "mermaid" / "mermaid.min.js",
        ASSETS_DIR / "fonts" / "Vazirmatn-Variable.woff2",
    ]
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise RuntimeError(f"فایل‌های لازم دانلود نشدند: {missing}")
    try:
        converters.build_reference_docx(str(ASSETS_DIR / "reference.docx"))
    except Exception:
        logger.exception("Building reference.docx failed; DOCX will use pandoc's default style")
    marker.write_text(ASSETS_VERSION)
    logger.info("Assets ready.")
