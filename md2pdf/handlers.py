"""md2pdf.handlers"""
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
import asyncio
import contextlib
import converters
import os
import tempfile
import zipfile
from md2pdf.config import (ACCENTS, ACCENT_LABELS, ALLOWED_USER_IDS, ASSETS_DIR, BOT_VERSION, CONVERSION_TIMEOUT, FONT_SIZES, IMAGE_MIME, MAX_DOCX_BYTES, MAX_DOCX_UNCOMPRESSED, MAX_IMAGE_BYTES, MAX_IMAGES_TOTAL, MAX_TEXT_BYTES, MAX_ZIP_BYTES, MAX_ZIP_ENTRIES, MAX_ZIP_UNCOMPRESSED, PDF_PAGE_FORMAT, TELEGRAM_UPLOAD_LIMIT, TEXT_EXTENSIONS, _active_users, conversion_semaphore, logger)
from md2pdf.html_build import (clean_filename, decode_text, error_detail)
from md2pdf.md_preprocess import (inject_images, prepare_markdown)
from md2pdf.pdf_render import (render_warnings, run_conversion, set_pdf_metadata)
from md2pdf.settings_store import (get_conversion_settings, get_output_format, get_user_setting, set_user_setting)




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




async def run_docx_conversion(md_text, out_path, title):
    prepared = prepare_markdown(md_text)
    reference = str(ASSETS_DIR / "reference.docx")
    async with conversion_semaphore:
        await asyncio.wait_for(
            asyncio.to_thread(
                converters.md_to_docx, prepared, out_path, title, reference, CONVERSION_TIMEOUT
            ),
            timeout=CONVERSION_TIMEOUT,
        )




async def send_file(message, path, filename):
    if os.path.getsize(path) > TELEGRAM_UPLOAD_LIMIT:
        raise ValueError("فایل بزرگ‌تر از حد مجاز ارسال تلگرام است")
    with open(path, "rb") as fh:
        await message.reply_document(document=fh, filename=filename, write_timeout=120)




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
    accent = get_user_setting(chat_id, "accent", "blue")
    accent_btn = ACCENT_LABELS.get(accent, ACCENT_LABELS["blue"]).replace(" ", " رنگ: ", 1)
    front = get_user_setting(chat_id, "front", True)
    paper = get_user_setting(chat_id, "paper", True)
    front_btn = "📄 جلد و فهرست: روشن" if front else "📄 جلد و فهرست: خاموش"
    paper_btn = "🧾 پس‌زمینه کرم: روشن" if paper else "⬜ پس‌زمینه کرم: خاموش"
    output_btn = "📤 خروجی: Word" if get_output_format(chat_id) == "docx" else "📤 خروجی: PDF"

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
        [InlineKeyboardButton(accent_btn, callback_data="cycle_accent")],
        [
            InlineKeyboardButton(front_btn, callback_data="toggle_front"),
            InlineKeyboardButton(paper_btn, callback_data="toggle_paper"),
        ],
        [InlineKeyboardButton(output_btn, callback_data="toggle_output")],
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
    elif data == "cycle_accent":
        keys = list(ACCENTS)
        current = get_user_setting(chat_id, "accent", "blue")
        index = keys.index(current) if current in keys else 0
        set_user_setting(chat_id, "accent", keys[(index + 1) % len(keys)])
    elif data == "toggle_front":
        current = get_user_setting(chat_id, "front", True)
        set_user_setting(chat_id, "front", not current)
    elif data == "toggle_paper":
        current = get_user_setting(chat_id, "paper", True)
        set_user_setting(chat_id, "paper", not current)
    elif data == "toggle_output":
        current = get_output_format(chat_id)
        set_user_setting(chat_id, "output", "pdf" if current == "docx" else "docx")

    await show_menu(update)




async def process_conversion(update: Update, context: ContextTypes.DEFAULT_TYPE, md_text: str, file_default_name=None):
    message = update.message
    chat_id = update.effective_chat.id
    output = get_output_format(chat_id)
    settings = {**get_conversion_settings(chat_id), "title": None}
    file_title = clean_filename(file_default_name) or f"Note_{message.message_id}"
    settings["title"] = file_title
    ext = "docx" if output == "docx" else "pdf"

    status_msg = await message.reply_text(f"⏳ در حال تبدیل {file_title}.{ext} ...")

    with tempfile.TemporaryDirectory(prefix="md2pdf_") as tmpdir:
        out_path = os.path.join(tmpdir, f"out.{ext}")
        try:
            stats = None
            if output == "docx":
                await run_docx_conversion(md_text, out_path, file_title)
            else:
                stats = await run_conversion(md_text, out_path, settings)
            await send_file(message, out_path, f"{file_title}.{ext}")
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




def _collect_zip_images(zf, infos):
    """عکس‌های ZIP را با محدودیت حجم می‌خواند؛ کلید: شناسهٔ IMG-01 (نام فایل بدون پسوند)."""
    images, skipped, total = {}, [], 0
    for info in infos:
        base = os.path.basename(info.filename)
        ext = os.path.splitext(base)[1].lower()
        stem = os.path.splitext(base)[0].upper()
        if info.filename.startswith("__MACOSX/") or base.startswith("._") or ext not in IMAGE_MIME:
            continue
        if not stem.startswith("IMG-") or stem in images:
            continue
        if info.file_size > MAX_IMAGE_BYTES or total + info.file_size > MAX_IMAGES_TOTAL:
            skipped.append(f"{base} (حجم زیاد)")
            continue
        with zf.open(info) as fh:
            data = fh.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            skipped.append(f"{base} (حجم زیاد)")
            continue
        total += len(data)
        images[stem] = (IMAGE_MIME[ext], data)
    return images, skipped


def read_zip_documents(zip_path):
    """فایل‌های متنی داخل ZIP را مستقیماً در حافظه و با محدودیت حجم می‌خواند (بدون extractall).
    عکس‌های IMG-xx داخل Markdown جایگذاری می‌شوند."""
    docs, skipped = [], []
    total = 0
    used_titles = {}

    with zipfile.ZipFile(zip_path) as zf:
        infos = sorted((i for i in zf.infolist() if not i.is_dir()), key=lambda i: i.filename)
        images, image_skipped = _collect_zip_images(zf, infos)
        skipped.extend(image_skipped)
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
            text = decode_text(data)
            if images:
                text, missing = inject_images(text, images)
                for ident in missing:
                    skipped.append(f"تصویر {ident} برای «{title}» داخل ZIP پیدا نشد")
            docs.append((title, text))
    return docs, skipped




async def handle_zip(update: Update, context: ContextTypes.DEFAULT_TYPE, zip_path: str, tmpdir: str):
    message = update.message
    chat_id = update.effective_chat.id
    output = get_output_format(chat_id)
    ext = "docx" if output == "docx" else "pdf"
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
        await safe_edit(status_msg, f"⏳ ({idx}/{len(docs)}) در حال تبدیل {title}.{ext} ...")
        out_path = os.path.join(tmpdir, f"zip_{idx}.{ext}")
        try:
            if output == "docx":
                await run_docx_conversion(text, out_path, title)
            else:
                stats = await run_conversion(text, out_path, {**settings, "title": title})
                warning = render_warnings(stats, title)
                if warning:
                    warnings.append(warning)
            await send_file(message, out_path, f"{title}.{ext}")
        except asyncio.TimeoutError:
            logger.warning("Conversion timed out for %s", title)
            failed.append(f"{title} (زمان تبدیل تمام شد)")
        except Exception as exc:
            logger.exception("Conversion failed for %s", title)
            failed.append(title + error_detail(exc))
        finally:
            with contextlib.suppress(OSError):
                os.remove(out_path)

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




def check_docx_archive(docx_path: str):
    """فایل .docx در واقع ZIP است؛ قبل از LibreOffice ساختار و حجم باز‌شده‌اش بررسی می‌شود."""
    if not zipfile.is_zipfile(docx_path):
        raise ValueError("فایل Word معتبر نیست")
    with zipfile.ZipFile(docx_path) as zf:
        total = sum(info.file_size for info in zf.infolist())
        if total > MAX_DOCX_UNCOMPRESSED:
            raise ValueError("حجم باز‌شدهٔ فایل Word بیش از حد مجاز است")
        if "word/document.xml" not in zf.namelist():
            raise ValueError("ساختار فایل Word معتبر نیست")




async def handle_docx(update: Update, context: ContextTypes.DEFAULT_TYPE, docx_path: str, tmpdir: str, filename: str):
    message = update.message
    file_title = clean_filename(os.path.splitext(filename or "")[0]) or f"Document_{message.message_id}"
    status_msg = await message.reply_text(f"⏳ در حال تبدیل {file_title}.docx به PDF ...")
    out_dir = os.path.join(tmpdir, "pdf")
    os.makedirs(out_dir, exist_ok=True)
    try:
        await asyncio.to_thread(check_docx_archive, docx_path)
        async with conversion_semaphore:
            pdf_path = await asyncio.wait_for(
                asyncio.to_thread(converters.docx_to_pdf, docx_path, out_dir, CONVERSION_TIMEOUT),
                timeout=CONVERSION_TIMEOUT + 10,
            )
        with contextlib.suppress(Exception):
            await asyncio.to_thread(set_pdf_metadata, pdf_path, file_title)
        await send_file(message, pdf_path, f"{file_title}.pdf")
        await safe_delete(status_msg)
    except (asyncio.TimeoutError, TimeoutError):
        logger.warning("Word conversion timed out for %s", file_title)
        await safe_edit(status_msg, f"❌ تبدیل {file_title} بیش از حد طول کشید و لغو شد.")
    except ValueError as exc:
        await safe_edit(status_msg, f"❌ {exc}")
    except Exception as exc:
        logger.exception("Word to PDF failed for %s", file_title)
        await safe_edit(status_msg, f"❌ خطا در تبدیل {file_title}.docx به PDF." + error_detail(exc))




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
    elif lower.endswith(".docx"):
        kind = "docx"
    elif not lower and mime in ("text/markdown", "text/x-markdown", "text/plain"):
        kind = "text"
    elif not lower and mime in ("application/zip", "application/x-zip-compressed"):
        kind = "zip"
    else:
        await update.message.reply_text("⛔ لطفاً فقط فایل .md، .txt، .zip یا .docx بفرستید.")
        return

    limit = {"zip": MAX_ZIP_BYTES, "docx": MAX_DOCX_BYTES}.get(kind, MAX_TEXT_BYTES)
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

            if kind == "docx":
                await handle_docx(update, context, local_path, tmpdir, filename)
            elif kind == "zip":
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




async def error_handler(update, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled error while processing an update", exc_info=context.error)
