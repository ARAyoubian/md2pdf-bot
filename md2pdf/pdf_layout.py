"""md2pdf.pdf_layout"""
from collections import Counter
import re
import unicodedata
from md2pdf.html_build import (_MARK_TOKEN_RE)




def find_marker_pages(pdf_path):
    """{اندیس عنوان: اندیس صفحهٔ 0-based} از روی نشانه‌های _mark_headings."""
    from pypdf import PdfReader

    found = {}
    for page_idx, page in enumerate(PdfReader(pdf_path).pages):
        for match in _MARK_TOKEN_RE.finditer(page.extract_text() or ""):
            found.setdefault(int(match.group(1)), page_idx)
    return found




def read_outline(pdf_path):
    """bookmark های PDF به ترتیب: [(عنوان، اندیس صفحهٔ 0-based)]."""
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    items = []

    def walk(nodes):
        for entry in nodes:
            if isinstance(entry, list):
                walk(entry)
                continue
            try:
                page = reader.get_destination_page_number(entry)
            except Exception:
                page = None
            items.append((" ".join(str(entry.title).split()), page))

    walk(reader.outline or [])
    return items




_ZERO_WIDTH_RE = re.compile("[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")




def _title_key(text):
    """
    کلید مقایسهٔ عنوان بین متن Markdown و bookmark های PDF:
    یکسان‌سازی یونیکد، حروف عربی/فارسی (ي→ی، ك→ک)، حذف نیم‌فاصله و نشانه‌های جهت،
    و بی‌توجهی به ترتیب کلمات و علائم نگارشی.
    """
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\u064a", "\u06cc").replace("\u0643", "\u06a9").replace("\u0629", "\u0647")
    text = _ZERO_WIDTH_RE.sub("", text)
    return tuple(sorted(re.sub(r"[^\w]+", " ", text).split()))




def _letters(text):
    """فقط حروف و ارقام (بدون فاصله و علامت) برای مقایسهٔ چندمجموعه‌ای."""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\u064a", "\u06cc").replace("\u0643", "\u06a9")
    text = _ZERO_WIDTH_RE.sub("", text).lower()
    return Counter(ch for ch in text if ch.isalnum())




def map_headings_to_pages(headings, outline):
    """
    نگاشت عنوان‌ها به صفحه از روی bookmark ها (به ترتیب سند).
    1) تطابق کامل کلمات؛ 2) اگر نشد: حروف عنوان در bookmark باشد (bookmark های PDF
    گاهی کلمات را بهم می‌چسبانند یا حروف لاتین اضافه دارند).
    """
    result, cursor = {}, 0
    keys = [_title_key(title) for title, _ in outline]
    letter_bags = [_letters(title) for title, _ in outline]
    for h in headings:
        want = _title_key(h["text"])
        want_letters = _letters(h["text"])
        match = None
        for j in range(cursor, len(outline)):
            if outline[j][1] is not None and keys[j] == want:
                match = j
                break
        if match is None and sum(want_letters.values()) >= 3:
            for j in range(cursor, len(outline)):
                if outline[j][1] is not None and (want_letters - letter_bags[j]) == Counter():
                    match = j
                    break
        if match is not None:
            result[h["id"]] = outline[match][1]
            cursor = match + 1
    if len(result) < len(headings) and len(outline) == len(headings):
        for h, (_, page) in zip(headings, outline):
            if h["id"] not in result and page is not None:
                result[h["id"]] = page
    return result




def build_front_info(headings, heading_pages):
    if not heading_pages:
        return None
    front_count = min(heading_pages.values())
    chapter_level = 1 if any(h["level"] == 1 for h in headings) else 2
    chapters = sorted(
        (heading_pages[h["id"]], h["text"])
        for h in headings
        if h["level"] == chapter_level and h["id"] in heading_pages
    )
    return {"front_count": front_count, "chapters": chapters}




def build_page_meta(total, front_info):
    """برای هر صفحه: (نمایش فوتر؟, متن هدر)."""
    if not front_info:
        return None
    front, chapters = front_info["front_count"], front_info["chapters"]
    meta = []
    for i in range(total):
        if i < front:
            meta.append((False, ""))
            continue
        current = ""
        for idx, text in chapters:
            if idx <= i:
                current = text
        meta.append((True, current))
    return meta
