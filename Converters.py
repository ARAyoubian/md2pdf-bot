"""
تبدیل‌دهنده‌های اضافی ربات (غیر از Markdown → PDF که در bot.py است).

    md_to_docx(...)              Markdown  → Word (.docx)   با pandoc
    build_reference_docx(...)    ساخت قالب Word فارسی (RTL، فونت Vazirmatn)
    docx_to_pdf(...)             Word (.docx) → PDF        با LibreOffice (headless)

این ماژول هیچ وابستگی به bot.py ندارد. پیش‌پردازش مشترک Markdown (فرمول‌ها و ...)
را bot.py قبل از صدا زدن این توابع انجام می‌دهد.
"""
import os
import re
import shutil
import subprocess
import tempfile

# ───────────────────────────── یافتن باینری‌ها ─────────────────────────────


def find_pandoc():
    """ابتدا pandoc همراه pypandoc-binary، و اگر نبود pandoc سیستمی."""
    try:
        import pypandoc

        return pypandoc.get_pandoc_path()
    except Exception:
        found = shutil.which("pandoc")
        if not found:
            raise RuntimeError("pandoc پیدا نشد (pypandoc-binary نصب نیست)")
        return found


def find_soffice():
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError("LibreOffice (soffice) پیدا نشد")


# ───────────────────────────── Markdown → DOCX ─────────────────────────────

PANDOC_FROM = "markdown-raw_html+tex_math_dollars+pipe_tables+fenced_code_blocks+strikeout+footnotes"

CALLOUT_WORD_LABELS = {
    "NOTE": "📌 نکته:",
    "WARNING": "⚠️ هشدار:",
    "TIP": "💡 پیشنهاد:",
    "IMPORTANT": "🔥 مهم:",
}
_CALLOUT_START_RE = re.compile(r"^\s*>\s*\[!(NOTE|WARNING|TIP|IMPORTANT)\]\s*$", re.IGNORECASE)
_QUOTE_PREFIX_RE = re.compile(r"^\s*>\s?")


def _docx_friendly_markdown(md_text: str) -> str:
    """
    callout های `> [!NOTE]` را به یک برچسب بولد و پاراگراف‌های عادی تبدیل می‌کند.
    (نقل‌قول‌های چندخطی بدون `>` اضافه می‌شوند تا در Word متن تمیز بماند.)
    """
    out = []
    lines = md_text.split("\n")
    i = 0
    while i < len(lines):
        match = _CALLOUT_START_RE.match(lines[i])
        if not match:
            out.append(lines[i])
            i += 1
            continue
        label = CALLOUT_WORD_LABELS[match.group(1).upper()]
        out.append(f"**{label}**")
        out.append("")
        i += 1
        while i < len(lines) and lines[i].lstrip().startswith(">"):
            out.append(_QUOTE_PREFIX_RE.sub("", lines[i], count=1))
            i += 1
        out.append("")
    return "\n".join(out)


def md_to_docx(md_text: str, out_path: str, title: str = "", reference_doc: str = None, timeout: int = 90) -> str:
    """Markdown را به .docx تبدیل می‌کند. فرمول‌ها به معادلهٔ قابل ویرایش Word تبدیل می‌شوند."""
    pandoc = find_pandoc()
    cmd = [
        pandoc,
        "--from", PANDOC_FROM,
        "--to", "docx",
        "--output", out_path,
        "--metadata", "lang=fa",
        "--metadata", "dir=rtl",
    ]
    if title:
        cmd += ["--metadata", f"title={title}"]
    if reference_doc and os.path.isfile(reference_doc):
        cmd += ["--reference-doc", reference_doc]

    source = _docx_friendly_markdown(md_text)
    result = subprocess.run(
        cmd,
        input=source.encode("utf-8"),
        capture_output=True,
        timeout=timeout,
    )
    if result.returncode != 0 or not os.path.isfile(out_path):
        raise RuntimeError(f"pandoc failed: {result.stderr.decode('utf-8', 'replace')[:300]}")
    return out_path


# ───────────────────────────── قالب Word فارسی ─────────────────────────────

FARSI_FONT = "Vazirmatn"


def build_reference_docx(out_path: str, font_name: str = FARSI_FONT) -> str:
    """
    قالب پیش‌فرض pandoc را می‌گیرد و آن را برای فارسی تنظیم می‌کند:
    همهٔ استایل‌های پاراگراف راست‌به‌چپ، فونت فارسی برای بخش‌های complex-script،
    و جهت راست‌به‌چپ برای بخش صفحه.
    """
    from docx import Document
    from docx.enum.style import WD_STYLE_TYPE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    pandoc = find_pandoc()
    default_path = out_path + ".default.docx"
    with open(default_path, "wb") as fh:
        subprocess.run([pandoc, "--print-default-data-file", "reference.docx"], stdout=fh, check=True, timeout=60)

    doc = Document(default_path)

    def set_fonts(rpr):
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts")
            rpr.insert(0, rfonts)
        for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            rfonts.set(qn(attr), font_name)
        for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:cstheme", "w:eastAsiaTheme"):
            if rfonts.get(qn(attr)) is not None:
                del rfonts.attrib[qn(attr)]

    for style in doc.styles:
        try:
            element = style.element
            if style.type == WD_STYLE_TYPE.PARAGRAPH:
                ppr = element.get_or_add_pPr()
                if ppr.find(qn("w:bidi")) is None:
                    ppr.append(OxmlElement("w:bidi"))
            if style.type in (WD_STYLE_TYPE.PARAGRAPH, WD_STYLE_TYPE.CHARACTER):
                rpr = element.get_or_add_rPr()
                set_fonts(rpr)
                if rpr.find(qn("w:rtl")) is None:
                    rpr.append(OxmlElement("w:rtl"))
        except Exception:
            continue

    for section in doc.sections:
        sectpr = section._sectPr
        if sectpr.find(qn("w:bidi")) is None:
            sectpr.append(OxmlElement("w:bidi"))

    doc.save(out_path)
    try:
        os.remove(default_path)
    except OSError:
        pass
    return out_path


# ───────────────────────────── DOCX → PDF (LibreOffice) ─────────────────────────────
# این بخش از همین حالا آماده است؛ Dockerfile و requirements.txt با LibreOffice و
# فونت‌ها آماده‌اند و برای فعال کردن آن نیازی به تغییر آن‌ها نیست.


def docx_to_pdf(docx_path: str, out_dir: str, timeout: int = 120) -> str:
    """Word را با LibreOffice به PDF تبدیل می‌کند و مسیر PDF را برمی‌گرداند."""
    soffice = find_soffice()
    profile_dir = tempfile.mkdtemp(prefix="lo_profile_")
    try:
        cmd = [
            soffice,
            f"-env:UserInstallation=file://{profile_dir}",
            "--headless",
            "--norestore",
            "--convert-to", "pdf",
            "--outdir", out_dir,
            docx_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
        base = os.path.splitext(os.path.basename(docx_path))[0]
        pdf_path = os.path.join(out_dir, base + ".pdf")
        if result.returncode != 0 or not os.path.isfile(pdf_path):
            raise RuntimeError(f"LibreOffice failed: {result.stderr.decode('utf-8', 'replace')[:300]}")
        return pdf_path
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)
