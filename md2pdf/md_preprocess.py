"""md2pdf.md_preprocess"""
import re




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
    "EXAMPLE": ("example", "🩺 مثال بالینی:"),
    "CLINICAL": ("clinical", "🧠 نکته بالینی:"),
    "REVIEW": ("review", "❓ سؤال مرور:"),
}


CALLOUT_ALERT_RE = re.compile(
    r"<blockquote>\s*<p>\s*\[!(NOTE|WARNING|TIP|IMPORTANT|EXAMPLE|CLINICAL|REVIEW)\]\s*(?:<br\s*/?>)?\s*",
    re.IGNORECASE,
)


CALLOUT_EMOJI_RE = re.compile(
    r"<blockquote>\s*<p>\s*(?:<strong>)?\s*(📌|⚠\ufe0f?|💡|🔥)"
)


EMOJI_CALLOUT_CLASS = {"📌": "note", "⚠": "warning", "💡": "tip", "🔥": "important", "🩺": "example", "🧠": "clinical", "❓": "review"}




_CALLOUT_LINE_START_RE = re.compile(r"^\s*>\s*\[!(?:NOTE|WARNING|TIP|IMPORTANT|EXAMPLE|CLINICAL|REVIEW)\]", re.IGNORECASE)




def _separate_callouts(md_text: str) -> str:
    """
    Python-Markdown دو blockquote پشت‌سرهم (با خط خالی) را یکی می‌کند.
    قبل از هر callout یک توضیح HTML (که nh3 حذفش می‌کند) می‌گذاریم تا جدا بماند.
    """
    out = []
    for line in md_text.split("\n"):
        if _CALLOUT_LINE_START_RE.match(line):
            out.append("")
            out.append("<!-- callout -->")
        out.append(line)
    return "\n".join(out)




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




def prepare_markdown(md_text: str) -> str:
    """پیش‌پردازش مشترک Markdown برای همهٔ خروجی‌ها (فرمول‌های escape‌شده و ...)."""
    text = unescape_escaped_math(md_text)
    text = normalize_display_math(text)
    return auto_repair_latex(text)
