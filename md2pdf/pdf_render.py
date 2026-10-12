"""md2pdf.pdf_render"""
from playwright.async_api import async_playwright
import asyncio
import contextlib
import gc
import html
import io
import os
import secrets
from urllib.parse import unquote, urlparse
from md2pdf.config import (ALLOW_REMOTE_IMAGES, ASSETS_DIR, BOT_VERSION, BRAND_FOOTER, BRAND_NAME, CHANNEL_HANDLE, CONVERSION_TIMEOUT, JS_HEAP_MB, PDF_PAGE_FORMAT, RENDER_TIMEOUT_MS, conversion_semaphore, logger)
from md2pdf.html_build import (ASSET_PREFIX, build_html, persian_date_text, text_direction, to_persian_digits)
from md2pdf.pdf_layout import (build_front_info, build_page_meta, find_marker_pages, map_headings_to_pages, read_outline)


browser_lock = asyncio.Lock()


global_browser = None


playwright_instance = None



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
        font_faces: Array.from(document.fonts).map((f) => f.family + ' ' + f.weight + ': ' + f.status),
        math_error_count: errors.length,
        math_errors: errors.slice(0, 20),
    };
}
"""



FOOTER_URL = "http://render.invalid/footer.html"


PAPER_URL = "http://render.invalid/paper.html"


PAPER_COLOR = "#fbf8f1"


PAPER_BG_TEMPLATE = """<!DOCTYPE html>
<html style="background: {{COLOR}}"><head><meta charset="utf-8">
<style>@page { margin: 0; } html, body { margin: 0; padding: 0; min-height: 100%; background: {{COLOR}}; }</style>
</head><body></body></html>
"""


PAGE_SIZES_MM = {"A4": (210.0, 297.0), "Letter": (215.9, 279.4)}



FOOTER_OVERLAY_TEMPLATE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
@font-face {
    font-family: 'VazirmatnWeb';
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
    font-family: 'VazirmatnWeb', 'Vazirmatn', 'Noto Sans Arabic', sans-serif;
    font-size: 8.5pt;
    color: #777777;
}
.hd { position: absolute; top: 9mm; left: {{PAD}}; right: {{PAD}}; text-align: center; font-family: 'VazirmatnWeb', 'Vazirmatn', 'Noto Sans Arabic', sans-serif; font-size: 8pt; color: #777777; border-bottom: 0.2pt solid #b0b0b0; padding-bottom: 2mm; }
.ttl { max-width: 45%; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.brand { font-size: 7.5pt; letter-spacing: 0.3px; direction: ltr; }
</style></head><body>{{PAGES}}</body></html>
"""




def build_footer_overlay(total, title, pad, width_mm, height_mm, meta=None):
    """یک صفحهٔ HTML: برای هر صفحهٔ PDF یک بلوک با هدر (در صورت نیاز) و فوتر (در صورت نیاز)."""
    safe_title = html.escape(title or "")
    if meta is None:
        meta = [(True, "")] * total
    parts = []
    for i in range(1, total + 1):
        show_footer, header = meta[i - 1] if i - 1 < len(meta) else (True, "")
        block = ['<div class="pg">']
        if header:
            block.append(f'<div class="hd" dir="{text_direction(header)}">{html.escape(header)}</div>')
        if show_footer:
            block.append(
                f'<div class="ft"><span class="ttl" dir="{text_direction(title)}">{safe_title}</span>'
                f'<span class="brand">{html.escape(BRAND_FOOTER)}</span>'
                f"<span>صفحه {to_persian_digits(i)} از {to_persian_digits(total)}</span></div>"
            )
        block.append("</div>")
        parts.append("".join(block))
    return (
        FOOTER_OVERLAY_TEMPLATE.replace("{{W}}", f"{width_mm:.2f}")
        .replace("{{H}}", f"{height_mm - 1:.2f}")
        .replace("{{PAD}}", pad)
        .replace("{{PAGES}}", "".join(parts))
    )




def count_pdf_pages(pdf_path: str) -> int:
    from pypdf import PdfReader

    return len(PdfReader(pdf_path).pages)




def set_pdf_metadata(pdf_path: str, title: str = "") -> None:
    """Author / Creator / Producer / Subject را روی برند کانال می‌گذارد."""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(pdf_path))
    writer.add_metadata({
        "/Title": title or "",
        "/Author": BRAND_NAME,
        "/Creator": BRAND_NAME,
        "/Producer": BRAND_NAME,
        "/Subject": CHANNEL_HANDLE,
        "/Keywords": f"{BRAND_NAME}, {CHANNEL_HANDLE}",
    })
    tmp_path = pdf_path + ".meta.tmp"
    with open(tmp_path, "wb") as fh:
        writer.write(fh)
    os.replace(tmp_path, pdf_path)




def count_bookmarks(pdf_path: str) -> int:
    """تعداد bookmark های PDF؛ -1 یعنی pypdf در دسترس نیست یا خواندن ناموفق بود."""
    try:
        from pypdf import PdfReader

        def walk(items):
            total = 0
            for item in items:
                total += walk(item) if isinstance(item, list) else 1
            return total

        return walk(PdfReader(pdf_path).outline)
    except Exception:
        return -1




def stamp_footer(pdf_path: str, overlay_bytes: bytes, bg_bytes: bytes = None) -> None:
    """هدر/فوتر را روی صفحات می‌نشاند و (اختیاری) رنگ کاغذ را زیر کل صفحه می‌گذارد."""
    from pypdf import PdfReader, PdfWriter

    base = PdfReader(pdf_path)
    overlay = PdfReader(io.BytesIO(overlay_bytes))
    bg_page = PdfReader(io.BytesIO(bg_bytes)).pages[0] if bg_bytes else None
    writer = PdfWriter(clone_from=base)
    for index, page in enumerate(writer.pages):
        if bg_page is not None:
            page.merge_page(bg_page, over=False)
        if index < len(overlay.pages):
            page.merge_page(overlay.pages[index])
    tmp_path = pdf_path + ".stamp.tmp"
    with open(tmp_path, "wb") as fh:
        writer.write(fh)
    os.replace(tmp_path, pdf_path)




async def add_footer(context, documents, pdf_path, title, page_format, orientation, pad, front_info=None, paper_color=None):
    """فوتر و هدر فارسی؛ اگر هر مرحله خطا بدهد PDF بدون آن‌ها می‌ماند. وضعیت را برمی‌گرداند."""
    try:
        size = PAGE_SIZES_MM.get(page_format)
        if size is None:
            logger.warning("Footer skipped: unknown page format %s", page_format)
            return f"skipped: unknown page format {page_format}"
        width_mm, height_mm = size
        if orientation == "landscape":
            width_mm, height_mm = height_mm, width_mm

        total = await asyncio.to_thread(count_pdf_pages, pdf_path)
        if total < 1:
            return "skipped: empty pdf"
        meta = build_page_meta(total, front_info)
        documents[FOOTER_URL] = build_footer_overlay(total, title, pad, width_mm, height_mm, meta)

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

        bg_bytes = None
        if paper_color:
            documents[PAPER_URL] = PAPER_BG_TEMPLATE.replace("{{COLOR}}", paper_color)
            bg_page = await context.new_page()
            bg_page.set_default_timeout(RENDER_TIMEOUT_MS)
            await bg_page.goto(PAPER_URL, wait_until="load")
            bg_bytes = await bg_page.pdf(
                format=page_format,
                landscape=(orientation == "landscape"),
                print_background=True,
                margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
            )
            await bg_page.close()

        await asyncio.to_thread(stamp_footer, pdf_path, overlay_bytes, bg_bytes)
        return "ok"
    except Exception as exc:
        logger.exception("Footer stamping failed; keeping PDF without footer")
        return f"failed: {type(exc).__name__}: {str(exc)[:200]}"




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
    ".ttf": "font/ttf",
    ".otf": "font/otf",
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




async def render_pdf(context, documents, full_html, has_math, has_mermaid, out_path, page_format, orientation, margin):
    """یک صفحه را رندر و PDF می‌کند. هر بار URL تازه تا کش مرورگر دخالت نکند."""
    url = f"http://render.invalid/doc-{secrets.token_hex(6)}.html"
    documents[url] = full_html
    page = await context.new_page()
    try:
        page.set_default_timeout(RENDER_TIMEOUT_MS)
        await page.goto(url, wait_until="load")
        await page.evaluate(RENDER_JS, {"math": has_math, "useMermaid": has_mermaid})
        stats = await page.evaluate(RENDER_STATS_JS)
        logger.info("render stats: %s (version %s)", stats, BOT_VERSION)
        if has_math and stats.get("arith", 0) > 0 and stats.get("mjx", 0) == 0:
            raise RuntimeError("MathJax did not render any formula")
        await page.pdf(
            path=out_path,
            format=page_format,
            landscape=(orientation == "landscape"),
            print_background=True,
            outline=True,
            tagged=True,
            margin={
                "top": margin,
                "bottom": margin,
                "left": margin,
                "right": margin,
            },
        )
    finally:
        with contextlib.suppress(Exception):
            await page.close()
    return stats




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
    template="classic",
    accent="blue",
    front=False,
    paper=True,
):
    page_format = page_format or PDF_PAGE_FORMAT
    page_margin = "12mm" if compact else "20mm"
    build_kw = dict(
        orientation=orientation,
        compact=compact,
        columns=columns,
        font_size=font_size,
        print_mode=print_mode,
        template=template,
        accent=accent,
        paper=paper,
        title=title,
        front=front,
        date_text=persian_date_text() if front else "",
    )

    browser = await ensure_browser()
    context = await browser.new_context(service_workers="block")
    documents = {}
    try:
        await context.route("**/*", make_router(documents))
        full_html, has_math, has_mermaid, headings = await asyncio.to_thread(
            build_html, md_text, mark_headings=bool(front), **build_kw
        )

        front_info = None
        heading_diag = None
        if front and headings:
            # مرحلهٔ اول: پیدا کردن صفحهٔ هر عنوان از روی bookmark ها
            pass1 = output_pdf_path + ".pass1.pdf"
            await render_pdf(context, documents, full_html, has_math, has_mermaid,
                             pass1, page_format, orientation, page_margin)
            try:
                marker_pages = await asyncio.to_thread(find_marker_pages, pass1)
            except Exception:
                logger.exception("Reading heading markers failed")
                marker_pages = {}
            try:
                outline = await asyncio.to_thread(read_outline, pass1)
            except Exception:
                logger.exception("Reading PDF outline failed")
                outline = []
            finally:
                with contextlib.suppress(OSError):
                    os.remove(pass1)

            # اولویت با نشانه‌ها؛ برای عنوان‌هایی که پیدا نشدند، از bookmark ها استفاده می‌شود
            outline_pages = map_headings_to_pages(headings, outline)
            heading_pages = {}
            for i, h in enumerate(headings):
                if i in marker_pages:
                    heading_pages[h["id"]] = marker_pages[i]
                elif h["id"] in outline_pages:
                    heading_pages[h["id"]] = outline_pages[h["id"]]
            heading_diag = {
                "headings": len(headings),
                "markers": len(marker_pages),
                "outline_items": len(outline),
                "mapped": len(heading_pages),
            }
            logger.info("heading mapping: %s", heading_diag)
            # مرحلهٔ دوم: فهرست با شماره‌صفحه
            full_html, has_math, has_mermaid, headings = await asyncio.to_thread(
                build_html, md_text, toc_pages=heading_pages, **build_kw
            )
            front_info = build_front_info(headings, heading_pages)

        stats = await render_pdf(context, documents, full_html, has_math, has_mermaid,
                                 output_pdf_path, page_format, orientation, page_margin)
        bookmarks_before = await asyncio.to_thread(count_bookmarks, output_pdf_path)
        footer_status = await add_footer(
            context, documents, output_pdf_path, title, page_format, orientation,
            page_margin, front_info,
            PAPER_COLOR if (paper and not print_mode) else None,
        )
        stats["footer"] = footer_status
        stats["bookmarks_before_footer"] = bookmarks_before
        stats["bookmarks"] = await asyncio.to_thread(count_bookmarks, output_pdf_path)
        try:
            await asyncio.to_thread(set_pdf_metadata, output_pdf_path, title)
        except Exception:
            logger.exception("Setting PDF metadata failed")
        stats["front_matter"] = bool(front_info)
        stats["heading_diag"] = heading_diag
        stats["paper_bg"] = bool(paper and not print_mode)
        logger.info("footer=%s bookmarks=%s->%s front=%s", footer_status,
                    bookmarks_before, stats["bookmarks"], bool(front_info))
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
