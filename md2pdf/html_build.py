"""md2pdf.html_build"""
from pygments.formatters import HtmlFormatter
import base64
from datetime import datetime, timedelta, timezone
import html
import markdown
import nh3
import re
import secrets
from md2pdf.config import (ACCENTS, BRAND_FOOTER, BRAND_NAME, DEBUG_ERRORS, LOGO_CANDIDATES)
from md2pdf.md_preprocess import (MERMAID_FENCE_RE, _separate_callouts, apply_callouts, auto_repair_latex, clean_mermaid_script, normalize_display_math, unescape_escaped_math)



CODE_STYLE_LIGHT = HtmlFormatter(style="friendly").get_style_defs(".codehilite")


CODE_STYLE_PRINT = HtmlFormatter(style="bw").get_style_defs(".codehilite")


# ایموجی‌های رنگی (📌 ⚠️ 💡 🔥 ...) در چاپ سیاه‌وسفید باید خاکستری شوند
EMOJI_RE = re.compile(
    "(?:[\U0001F000-\U0001FAFF\u2600-\u27BF\u2300-\u23FF\u2B00-\u2BFF\u2190-\u21FF\u00A9\u00AE]\uFE0F?)+"
)




# ───────────────────────────── قالب HTML ─────────────────────────────

DOC_URL = "http://render.invalid/doc.html"


ASSET_PREFIX = "http://render.invalid/assets/"



HTML_TEMPLATE = r"""<!DOCTYPE html>
<html dir="ltr">  <!-- ریشهٔ RTL در چاپ Chromium محتوا را ~۵mm به چپ می‌برد؛ جهت هر بلوک با dir=auto تعیین می‌شود -->
<head>
    <meta charset="utf-8">
    <style>
        @font-face {
            font-family: 'VazirmatnWeb';
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
            font-family: 'VazirmatnWeb', 'Vazirmatn', 'Noto Sans Arabic', 'Segoe UI', Roboto, sans-serif;
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
        .figure { break-inside: avoid; page-break-inside: avoid; }
        /* عکس و توضیح زیرش وسط‌چین */
        p:has(> img), p:has(> em:only-child) { text-align: center; }

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
            --border-color: #999999;
            --note-bg: #ffffff; --warning-bg: #ffffff;
            --tip-bg: #ffffff; --important-bg: #ffffff;
            --note-border: #555555; --warning-border: #111111;
            --tip-border: #777777; --important-border: #000000;
            --accent-color: #222222;
            --text-main: #000000;
            --text-muted: #555555;
        }
        body.print-mode th { background-color: #eeeeee; }
        body.print-mode .toc-dots { border-bottom-color: #888888; }
        body.print-mode a { color: #000000; text-decoration: underline; }
        body.print-mode .emo { filter: grayscale(100%); }
        body.print-mode .cover-logo,
        body.print-mode .mermaid-diagram,
        body.print-mode .mermaid-diagram svg { filter: grayscale(100%); }
        body.print-mode blockquote[class*="callout-"] > p:first-child > strong:first-child { color: #ffffff; }
        body.print-mode blockquote {
            border: 1px solid #999999;
            border-inline-start: 4px solid #333333 !important;
        }

        /* ───── رنگ تأکیدی ───── */
        h2 { color: var(--accent-color); }
        th { color: var(--accent-color); }
        th { background-color: color-mix(in srgb, var(--accent-color) 14%, #ffffff); }
        tr:nth-child(even) { background-color: color-mix(in srgb, var(--accent-color) 5%, #ffffff); }

        /* ───── پس‌زمینهٔ کاغذی ───── */
        body:not(.print-mode) { background-color: #fbf8f1; } /* همان PAPER_COLOR */
        body.paper-off, body.print-mode { background-color: #ffffff; }

        /* ───── خط‌های جدا در یک پاراگراف ───── */
        span.ln { display: block; }

        /* ───── نشان عنوان‌دار callout ───── */
        blockquote[class*="callout-"] > p:first-child > strong:first-child {
            display: inline-block;
            color: #ffffff;
            padding: 1px 10px;
            border-radius: 999px;
            font-size: 0.9em;
            margin-inline-end: 6px;
        }
        blockquote.callout-note > p:first-child > strong:first-child { background: var(--note-border); }
        blockquote.callout-warning > p:first-child > strong:first-child { background: var(--warning-border); }
        blockquote.callout-tip > p:first-child > strong:first-child { background: var(--tip-border); }
        blockquote.callout-important > p:first-child > strong:first-child { background: var(--important-border); }

        /* ───── کادر خلاصهٔ فصل ───── */
        .chapter-summary {
            border: 1.5px solid var(--accent-color);
            border-radius: 10px;
            padding: 4px 16px 10px;
            margin: 18px 0;
        }
        .chapter-summary > h2, .chapter-summary > h3 {
            border-bottom: none;
            color: var(--accent-color);
            margin-top: 10px;
        }
        body.print-mode .chapter-summary { background: none; }

        /* ───── جلد ───── */
        .cover {
            min-height: 225mm;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            text-align: center;
            break-after: page;
            page-break-after: always;
        }
        .cover-kicker { font-size: 13px; letter-spacing: 2px; color: var(--accent-color); margin-bottom: 18px; }
        .cover-title { font-size: 34px; font-weight: 700; line-height: 1.5; margin-bottom: 18px; }
        .cover-line { width: 80px; height: 3px; background: var(--accent-color); margin: 0 auto 18px; }
        .cover-meta { font-size: 13px; color: var(--text-muted); }
        .cover-logo { width: 46mm; max-width: 55%; height: auto; margin-bottom: 14px; }
        .cover-subtitle { font-size: 20px; font-weight: 700; margin-bottom: 14px; color: var(--text-main); }
        .cover-brand { margin-top: 22px; font-size: 12px; letter-spacing: 0.5px; color: var(--text-muted); direction: ltr; }

        /* ───── فهرست مطالب ───── */
        .toc { break-after: page; page-break-after: always; }
        .toc-title {
            text-align: right;
            font-size: 22px;
            font-weight: 700;
            color: var(--accent-color);
            border-bottom: 2px solid var(--border-color);
            padding-bottom: 8px;
            margin-bottom: 18px;
        }
        .toc-row { display: flex; align-items: baseline; gap: 6px; margin: 6px 0; font-size: 14px; }
        .toc-row a { color: var(--text-main); text-decoration: none; }
        .toc-row.toc-l1 { font-weight: 700; margin-top: 12px; }
        .toc-row.toc-l2 { padding-inline-start: 18px; }
        .toc-row.toc-l3 { padding-inline-start: 36px; font-size: 13px; color: var(--text-muted); }
        .toc-dots { flex: 1; border-bottom: 1px dotted #aeb4bb; transform: translateY(-3px); }
        .toc-num { min-width: 28px; text-align: start; }

        /* ───── r31: جلد با قاب رنگی ───── */
        .cover {
            border-top: 6px solid var(--accent-color);
            border-bottom: 6px solid var(--accent-color);
            padding: 12mm 0;
        }
        .cover-logo { width: 93mm; max-width: 90%; }
        .cover-title { font-size: 36px; font-weight: 800; color: var(--accent-color); }
        .cover-subtitle { font-size: 16px; font-weight: 400; color: var(--text-muted); margin-bottom: 14px; }

        /* ───── r31: جدول ───── */
        table {
            border-collapse: separate;
            border-spacing: 0;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            box-shadow: none;
        }
        th, td { border: none; border-bottom: 1px solid var(--border-color); }
        th + th, td + td { border-inline-start: 1px solid var(--border-color); }
        th { border-bottom: 2px solid var(--accent-color); }
        thead th:first-child { border-start-start-radius: 8px; }
        thead th:last-child { border-start-end-radius: 8px; }
        tbody tr:last-child td { border-bottom: none; }
        tbody tr:last-child td:first-child { border-end-start-radius: 8px; }
        tbody tr:last-child td:last-child { border-end-end-radius: 8px; }
        tr:nth-child(even) { background-color: color-mix(in srgb, var(--accent-color) 9%, #ffffff); }

        /* ───── r31: callout ───── */
        blockquote[class*="callout-"] { border-inline-start-width: 6px; padding: 14px 20px; }
        blockquote[class*="callout-"] > p:first-child > strong:first-child { font-size: 1em; padding: 3px 14px; }
        body.print-mode blockquote { border-inline-start-width: 6px !important; }

        .hm { font-size: 1px; color: #ffffff; }

        /* ───── r36: جداکننده بین مباحث بزرگ ───── */
        h2 {
            border-bottom: none;
            padding-bottom: 6px;
            background-image: linear-gradient(var(--accent-color), var(--accent-color));
            background-repeat: no-repeat;
            background-size: 48px 3px;
            background-position: right bottom;
        }

        /* ───── r36: انواع callout جدید ───── */
        blockquote.callout-example { background: var(--example-bg); border-inline-start-color: var(--example-border); }
        blockquote.callout-clinical { background: var(--clinical-bg); border-inline-start-color: var(--clinical-border); }
        blockquote.callout-review { background: var(--review-bg); border-inline-start-color: var(--review-border); border-style: dashed; border-width: 1px; border-inline-start-width: 6px; }
        blockquote.callout-example > p:first-child > strong:first-child { background: var(--example-border); }
        blockquote.callout-clinical > p:first-child > strong:first-child { background: var(--clinical-border); }
        blockquote.callout-review > p:first-child > strong:first-child { background: var(--review-border); }
        body:not(.print-mode) {
            --example-bg: #f0f7ff; --example-border: #2563a6;
            --clinical-bg: #effaf6; --clinical-border: #0f766e;
            --review-bg: #f5f3ff; --review-border: #6d5bd0;
        }
        body.print-mode {
            --example-bg: #ffffff; --example-border: #444444;
            --clinical-bg: #ffffff; --clinical-border: #666666;
            --review-bg: #ffffff; --review-border: #222222;
        }

        /* ───── r36: جدول با ستون برچسب رنگی ───── */
        th:first-child, td:first-child { width: 22%; }
        tbody td:first-child {
            background-color: color-mix(in srgb, var(--accent-color) 10%, #ffffff);
            font-weight: 700;
            color: var(--accent-color);
        }
        body.print-mode tbody td:first-child { color: #000000; }

        /* ───── انگلیسی همیشه Arial (در لینوکس: Liberation Sans با متریک یکسان) ───── */
        .en { font-family: Arial, 'Liberation Sans', Arimo, Helvetica, sans-serif; unicode-bidi: isolate; }

        /* PYGMENTS_INJECTION */
    </style>
    {{SCRIPTS}}
</head>
<body class="{{BODY_CLASSES}}" style="{{BODY_STYLE}}">
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


_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")




def to_persian_digits(value) -> str:
    return str(value).translate(_PERSIAN_DIGITS)



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




PERSIAN_CHAR_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")


LATIN_LETTER_RE = re.compile(r"[A-Za-z]")


_BLOCK_DIR_RE = re.compile(r"<(p|h[1-6]|li|blockquote|dt|dd|td|th|ul|ol|table)\b([^>]*)>(.*?)</\1>", re.S)




def text_direction(text: str) -> str:
    """
    قاعدهٔ جهت متن:
      • اگر حتی یک حرف فارسی/عربی (یا رقم فارسی) در متن باشد → راست‌به‌چپ
      • فقط اگر متن فقط لاتین باشد → چپ‌به‌راست
      • اگر حرفی در متن نباشد (مثلاً فقط علامت یا عدد لاتین) → راست‌به‌چپ (پیش‌فرض سند)
    """
    if PERSIAN_CHAR_RE.search(text or ""):
        return "rtl"
    if LATIN_LETTER_RE.search(text or ""):
        return "ltr"
    return "rtl"




_BR_RE = re.compile(r"<br\s*/?>", re.I)


_LINE_SPLIT_TAGS = ("p", "li", "td", "th", "blockquote", "dd", "dt")




def _split_lines_with_direction(inner_html: str) -> str:
    """
    هر خط (جدا شده با سطر شکسته) جهت خودش را می‌گیرد.
    بدون این کار، یک پاراگراف با چند خط فارسی و انگلیسی همه‌اش یک جهت می‌گرفت.
    """
    parts = []
    for segment in _BR_RE.split(inner_html):
        if not _plain_text(segment):
            continue
        parts.append(f'<span class="ln" dir="{text_direction(_plain_text(segment))}">{segment}</span>')
    return "".join(parts)




def apply_block_directions(html_text: str) -> str:
    """به هر بلوک، جهت را بر اساس متن خودش (با قاعدهٔ text_direction) می‌دهد."""

    def repl(match):
        tag, attrs, inner = match.group(1), match.group(2), match.group(3)
        attrs = re.sub(r'\s+dir="[^"]*"', "", attrs)
        direction = text_direction(_plain_text(inner))
        inner = apply_block_directions(inner)
        if tag in _LINE_SPLIT_TAGS and _BR_RE.search(inner):
            inner = _split_lines_with_direction(inner)
        return f'<{tag}{attrs} dir="{direction}">{inner}</{tag}>'

    return _BLOCK_DIR_RE.sub(repl, html_text)




IRAN_TZ = timezone(timedelta(hours=3, minutes=30))


PERSIAN_MONTHS = (
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
)




def gregorian_to_jalali(gy, gm, gd):
    """تبدیل تاریخ میلادی به شمسی (الگوریتم استاندارد)."""
    g_days_in_month = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
        + gd + g_days_in_month[gm - 1]
    )
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return jy, jm, jd




def persian_date_text(now=None):
    """تاریخ شمسی فقط ماه و سال، مثل «مهر ۱۴۰۵»."""
    now = now or datetime.now(IRAN_TZ)
    jy, jm, _jd = gregorian_to_jalali(now.year, now.month, now.day)
    return f"{PERSIAN_MONTHS[jm - 1]} {to_persian_digits(jy)}"




_HEADING_RE = re.compile(r"<h([1-3])\b([^>]*)>(.*?)</h\1>", re.S)


_ANY_HEADING_RE = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1>", re.S)




def _plain_text(fragment):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", fragment)).split())




def extract_headings(body_html):
    """عنوان‌های سطح ۱ تا ۳ با id (برای فهرست و هدر)."""
    found = []
    for m in _HEADING_RE.finditer(body_html):
        id_match = re.search(r'\bid="([^"]+)"', m.group(2))
        text = _plain_text(m.group(3))
        if id_match and text:
            found.append({"level": int(m.group(1)), "id": id_match.group(1), "text": text})
    return found




def wrap_chapter_summaries(body_html):
    """بخش «خلاصه» هر فصل (تا تیتر هم‌سطح بعدی) داخل کادر برجسته می‌رود."""
    heads = list(_ANY_HEADING_RE.finditer(body_html))
    spans = []
    for idx, m in enumerate(heads):
        level = int(m.group(1))
        text = _plain_text(m.group(2))
        if "خلاصه" not in text and "خلاصۀ" not in text:
            continue
        end = len(body_html)
        for nxt in heads[idx + 1:]:
            if int(nxt.group(1)) <= level:
                end = nxt.start()
                break
        if body_html[m.end():end].strip():
            spans.append((m.start(), m.end(), end))
    out, pos = [], 0
    for start, head_end, end in spans:
        if start < pos:
            continue
        out.append(body_html[pos:start])
        out.append('<div class="chapter-summary">' + body_html[start:head_end] + body_html[head_end:end] + "</div>")
        pos = end
    out.append(body_html[pos:])
    return "".join(out)




def _logo_data_uri() -> str:
    """لوگوی کانال به‌صورت data URI (بدون نیاز به درخواست شبکه یا مسیر فایل در مرورگر)."""
    for path in LOGO_CANDIDATES:
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")
    return ""




def build_front_matter(title, date_text, headings, toc_pages, doc_title="", logo_uri=""):
    """
    جلد (با لوگو، نام فایل، عنوان سند، ماه و سال و برند) و فهرست مطالب.
    toc_pages: {id: اندیس صفحهٔ 0-based}.
    """
    cover_parts = ['<section class="cover">']
    if logo_uri:
        cover_parts.append(f'<img class="cover-logo" src="{logo_uri}" alt="{BRAND_NAME}">')
    cover_parts.append('<div class="cover-kicker">جزوه</div>')
    cover_parts.append(
        f'<div class="cover-title" dir="{text_direction(title)}">{html.escape(title or "")}</div>'
    )
    if doc_title:
        cover_parts.append(
            f'<div class="cover-subtitle" dir="{text_direction(doc_title)}">{html.escape(doc_title)}</div>'
        )
    cover_parts.append('<div class="cover-line"></div>')
    cover_parts.append(f'<div class="cover-meta">{html.escape(date_text or "")}</div>')
    cover_parts.append(f'<div class="cover-brand">{html.escape(BRAND_FOOTER)}</div>')
    cover_parts.append("</section>")
    cover = "".join(cover_parts)

    if not headings:
        return cover

    rows = []
    for h in headings:
        page = (toc_pages or {}).get(h["id"])
        num = to_persian_digits(page + 1) if page is not None else "–"
        rows.append(
            f'<div class="toc-row toc-l{h["level"]}" dir="{text_direction(h["text"])}">'
            f'<a href="#{h["id"]}">{html.escape(h["text"])}</a>'
            f'<span class="toc-dots"></span><span class="toc-num">{num}</span></div>'
        )
    toc = '<section class="toc"><div class="toc-title" dir="rtl">فهرست مطالب</div>' + "".join(rows) + "</section>"
    return cover + toc




_MARK_TOKEN_RE = re.compile(r"zqm(\d+)zq")




def _mark_headings(body_html: str) -> str:
    """
    هر عنوان (با همان قاعدهٔ extract_headings) یک نشانهٔ نامرئی ASCII می‌گیرد: zqm<i>zq.
    این نشانه‌ها با استخراج متن PDF خوانا هستند و جای bookmark ها را می‌گیرند،
    چون bookmark ها برای بعضی عنوان‌های فارسی/مختلط درست نگاشت نمی‌شدند.
    """
    counter = 0

    def repl(match):
        nonlocal counter
        opening, level, inner, closing = match.group(1), match.group(2), match.group(3), match.group(4)
        id_match = re.search(r'\bid="([^"]+)"', opening)
        if not id_match or not _plain_text(inner):
            return match.group(0)
        token = f'<span class="hm">zqm{counter}zq</span>'
        counter += 1
        return f"{opening}{token}{inner}{token}{closing}"

    return re.sub(r"(<h([1-3])\b[^>]*>)(.*?)(</h\2>)", repl, body_html, flags=re.S)




_LATIN_TOKEN_RE = re.compile(r"&#?[A-Za-z0-9]+;|[A-Za-z0-9](?:[A-Za-z0-9 .,:'\u2019/+\-]*[A-Za-z0-9])?")


_SKIP_TAGS = ("pre", "code", "script", "style", "textarea")


_VOID_TAGS = ("br", "img", "hr", "meta", "input", "col", "wbr", "link")


_TAG_NAME_RE = re.compile(r"<\s*(/?)\s*([a-zA-Z0-9]+)([^>]*)>")




def apply_latin_spans(html_text: str) -> str:
    """
    متن لاتین را در <span class="en" dir="ltr"> می‌گذارد تا با Arial نمایش داده شود.
    داخل تگ‌ها، کد، پیش‌نمایش ریاضی (arithmatex) و mermaid دست‌نخورده می‌ماند.
    """
    parts = re.split(r"(<[^>]+>)", html_text)
    stack = []  # برای هر تگ باز: True اگر داخل محدوده‌ی بدون تغییر است
    skip_depth = 0
    out = []
    for part in parts:
        if part.startswith("<"):
            match = _TAG_NAME_RE.match(part)
            if match and not part.startswith("<!"):
                closing, name, attrs = match.group(1), match.group(2).lower(), match.group(3)
                if closing:
                    if stack:
                        was_skip = stack.pop()
                        if was_skip:
                            skip_depth -= 1
                elif name not in _VOID_TAGS and not attrs.rstrip().endswith("/"):
                    is_skip = name in _SKIP_TAGS or "arithmatex" in attrs or 'class="mermaid"' in attrs
                    stack.append(is_skip)
                    if is_skip:
                        skip_depth += 1
            out.append(part)
            continue
        if skip_depth:
            out.append(part)
        else:
            out.append(_LATIN_TOKEN_RE.sub(
                lambda m: m.group(0) if m.group(0).startswith("&")
                else f'<span class="en" dir="ltr">{m.group(0)}</span>',
                part,
            ))
    return "".join(out)




_FIGURE_RE = re.compile(
    r"<p[^>]*>\s*<img[^>]*>\s*</p>(?:\s*<p[^>]*>\s*<em>.*?</em>\s*</p>)?", re.S
)


def build_html(
    md_text,
    orientation="portrait",
    compact=False,
    columns=1,
    font_size="normal",
    print_mode=False,
    template="classic",
    accent="blue",
    paper=True,
    title="",
    front=False,
    toc_pages=None,
    date_text="",
    mark_headings=False,
):
    """Markdown → HTML کامل. خروجی: (html, has_math, has_mermaid, headings)"""
    # نمودارهای mermaid قبل از هر پردازش دیگری جدا می‌شوند و بعد از پاک‌سازی HTML برمی‌گردند
    token = "MMD" + secrets.token_hex(8) + "X"
    mermaid_blocks = []

    def stash_mermaid(match):
        mermaid_blocks.append(match.group(1).strip())
        return f"\n\n{token}{len(mermaid_blocks) - 1}END\n\n"

    md_text = MERMAID_FENCE_RE.sub(stash_mermaid, md_text)
    md_text = _separate_callouts(md_text)
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
    body = apply_block_directions(body)

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

    doc_title = ""
    if front:
        first_h1 = re.match(r"\s*<h1\b[^>]*>(.*?)</h1>", body, re.S)
        if first_h1:
            doc_title = _plain_text(first_h1.group(1))
            body = body[first_h1.end():]
    headings = extract_headings(body)
    if front and mark_headings:
        body = _mark_headings(body)
    body = wrap_chapter_summaries(body)
    if front and (headings or doc_title):
        body = build_front_matter(
            title, date_text, headings, toc_pages, doc_title=doc_title, logo_uri=_logo_data_uri()
        ) + body

    body = apply_latin_spans(body)
    # عکس و توضیح زیرش یک بلوک نشکن‌پذیر می‌شوند تا کنار هم بمانند
    body = _FIGURE_RE.sub(lambda m: '<div class="figure">' + m.group(0) + "</div>", body)
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
    if not paper:
        classes.append("paper-off")
    if print_mode:
        body = EMOJI_RE.sub(lambda m: f'<span class="emo">{m.group(0)}</span>', body)
    body_style = (
        "--accent-color: #222222"
        if print_mode
        else f"--accent-color: {ACCENTS.get(accent, ACCENTS['blue'])}"
    )

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
        HTML_TEMPLATE.replace("/* PYGMENTS_INJECTION */", CODE_STYLE_PRINT if print_mode else CODE_STYLE_LIGHT)
        .replace("{{SCRIPTS}}", scripts)
        .replace("{{BODY_CLASSES}}", " ".join(classes))
        .replace("{{BODY_STYLE}}", body_style)
        .replace("{{CONTENT}}", body)
    )
    return full_html, has_math, bool(mermaid_blocks), headings




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
