import os
import re
import json
import zipfile
import tempfile
import markdown
import threading
import asyncio
import gc
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler
)
from playwright.async_api import async_playwright
from pygments.formatters import HtmlFormatter

CODE_STYLE_LIGHT = HtmlFormatter(style="friendly").get_style_defs('.codehilite')

conversion_lock = asyncio.Lock()
global_browser = None
playwright_instance = None
SETTINGS_FILE = "user_settings.json"

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f)
    except Exception:
        pass

user_all_settings = load_settings()

def get_user_setting(chat_id, key, default):
    str_id = str(chat_id)
    if str_id in user_all_settings and key in user_all_settings[str_id]:
        return user_all_settings[str_id][key]
    return default

def set_user_setting(chat_id, key, value):
    str_id = str(chat_id)
    if str_id not in user_all_settings:
        user_all_settings[str_id] = {}
    user_all_settings[str_id][key] = value
    save_settings(user_all_settings)

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    class RequestHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(b"Bot is Running successfully on Back4App!")
    server = HTTPServer(('0.0.0.0', port), RequestHandler)
    server.serve_forever()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html dir="auto">
<head>
    <meta charset="utf-8">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&family=Vazirmatn:wght@400;500;600;700&display=swap" rel="stylesheet">
    
    <style>
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

        @page {
            size: letter {{PAGE_ORIENTATION}};
            margin: {{PAGE_MARGIN}};
            background-color: var(--bg-body);
        }

        body {
            background-color: var(--bg-body);
            font-family: 'Inter', 'Vazirmatn', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            color: var(--text-main);
            line-height: 1.7;
            padding: 0;
            margin: 0;
            font-size: 15px;
            letter-spacing: -0.01em;
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
        body > h1:first-of-type {
            page-break-before: avoid;
            break-before: avoid;
        }

        body.landscape-mode {
            max-width: 900px;
            margin: 0 auto;
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

        p { margin-bottom: 14px; }

        pre, .codehilite {
            background-color: var(--bg-code) !important;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 14px 16px;
            overflow-x: auto;
            direction: ltr !important;
            text-align: left !important;
            font-family: 'JetBrains Mono', monospace;
            font-size: 13.5px;
            line-height: 1.5;
            margin: 16px 0;
        }

        code {
            font-family: 'JetBrains Mono', monospace;
            background-color: var(--bg-code);
            border: 1px solid var(--border-color);
            padding: 2px 6px;
            border-radius: 5px;
            font-size: 85%;
            direction: ltr;
            display: inline-block;
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
            overflow: hidden;
            box-shadow: 0 0 0 1px var(--border-color);
        }

        th, td {
            padding: 10px 14px;
            border: 1px solid var(--border-color);
        }

        th {
            background-color: var(--bg-code);
            font-weight: 600;
            text-align: inherit;
        }

        tr:nth-child(even) {
            background-color: var(--table-even);
        }

        blockquote {
            margin: 16px 0;
            padding: 12px 18px;
            color: var(--text-main);
            border-inline-start: 4px solid var(--accent-color);
            background: var(--bg-code);
            border-radius: 0 6px 6px 0;
        }
        blockquote.callout-note { background-color: var(--note-bg); border-left-color: var(--note-border); }
        blockquote.callout-warning { background-color: var(--warning-bg); border-left-color: var(--warning-border); }
        blockquote.callout-tip { background-color: var(--tip-bg); border-left-color: var(--tip-border); }
        blockquote.callout-important { background-color: var(--important-bg); border-left-color: var(--important-border); }

        hr {
            height: 1px;
            background-color: var(--border-color);
            border: none;
            margin: 24px 0;
        }

        .toc {
            background: var(--bg-code);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 14px 20px;
            margin-bottom: 24px;
        }
        .toc ul { padding-inline-start: 20px; margin: 5px 0; }
        .toc a { color: var(--accent-color); text-decoration: none; }

        mjx-container {
            overflow-x: auto;
            overflow-y: hidden;
            max-width: 100%;
        }
        td mjx-container, th mjx-container {
            display: inline-block !important;
            margin: 0 !important;
        }

        /* PYGMENTS_INJECTION */
    </style>
    
    <script>
        window.MathJax = {
            tex: {
                inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
                displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']],
                processEscapes: true,
                processEnvironments: true
            },
            options: {
                skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
            },
            chtml: {
                scale: 0.95
            }
        };
    </script>
    <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>
</head>
<body class="{{BODY_CLASSES}}">
    {{content}}
</body>
</html>
"""

def process_callouts(md_text):
    md_text = re.sub(r'>\s*\[!NOTE\]', '<div class="callout-note-marker"></div>', md_text)
    md_text = re.sub(r'>\s*\[!WARNING\]', '<div class="callout-warning-marker"></div>', md_text)
    md_text = re.sub(r'>\s*\[!TIP\]', '<div class="callout-tip-marker"></div>', md_text)
    md_text = re.sub(r'>\s*\[!IMPORTANT\]', '<div class="callout-important-marker"></div>', md_text)
    
    md_text = md_text.replace('<div class="callout-note-marker"></div>', '<blockquote><strong>📌 نکته:</strong>')
    md_text = md_text.replace('<div class="callout-warning-marker"></div>', '<blockquote><strong>⚠️ هشدار:</strong>')
    md_text = md_text.replace('<div class="callout-tip-marker"></div>', '<blockquote><strong>💡 پیشنهاد:</strong>')
    md_text = md_text.replace('<div class="callout-important-marker"></div>', '<blockquote><strong>🔥 مهم:</strong>')
    return md_text

def extract_title_and_hashtag(text, default_name="Document"):
    hashtag_match = re.search(r'#([رعشگپتثجحخدذرزسشصطظعغفقکلمنوهیژآإأؤةءچپگژ۱۲۳۴۵۶۷۸۹۰a-zA-Z0-9_]+)', text)
    if hashtag_match:
        tag_name = hashtag_match.group(1).strip()
        if tag_name:
            clean_text = text.replace(f"#{tag_name}", "").strip()
            return tag_name, clean_text

    match = re.search(r'^#\s+(.+)$', text, re.MULTILINE)
    if match:
        clean = re.sub(r'[\\/*?:"<>|#]', '', match.group(1)).strip()
        if clean:
            return clean[:40], text
            
    return default_name, text

async def init_browser():
    global global_browser, playwright_instance
    if not global_browser:
        playwright_instance = await async_playwright().start()
        global_browser = await playwright_instance.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox', 
                '--disable-setuid-sandbox', 
                '--disable-dev-shm-usage', 
                '--disable-gpu',
                '--disable-extensions',
                '--js-flags="--max-old-space-size=128"'
            ]
        )
        print("✅ Global Browser Instance Initialized with RAM limits.")

async def generate_pdf_output(md_text, output_pdf_path, orientation="portrait", compact=False, columns=1):
    await init_browser()
    
    md_text = process_callouts(md_text)
    
    configs = {
        'codehilite': {
            'guess_lang': False,
            'css_class': 'codehilite'
        }
    }
    
    html_content = markdown.markdown(
        md_text, 
        extensions=['fenced_code', 'codehilite', 'tables', 'nl2br', 'mdx_math', 'toc'],
        extension_configs=configs
    )
    
    classes = []
    if compact:
        classes.append("compact-mode")
    if orientation == "landscape":
        classes.append("landscape-mode")
    if columns == 2:
        classes.append("columns-2")
    body_classes = " ".join(classes)
    
    page_margin = "12mm 12mm" if compact else "20mm 20mm"
    page_orientation = "landscape" if orientation == "landscape" else "portrait"
    
    full_html = HTML_TEMPLATE.replace('/* PYGMENTS_INJECTION */', CODE_STYLE_LIGHT)
    full_html = full_html.replace('{{BODY_CLASSES}}', body_classes)
    full_html = full_html.replace('{{content}}', html_content)
    full_html = full_html.replace('{{PAGE_MARGIN}}', page_margin)
    full_html = full_html.replace('{{PAGE_ORIENTATION}}', page_orientation)
    
    with tempfile.NamedTemporaryFile(delete=False, suffix='.html', mode='w', encoding='utf-8') as f:
        f.write(full_html)
        temp_html_path = f.name
        
    page = await global_browser.new_page()
    try:
        await page.goto(f"file://{temp_html_path}", wait_until="networkidle")
        await page.evaluate("""
            async () => {
                await document.fonts.ready;
                if (window.MathJax && window.MathJax.typesetPromise) {
                    await window.MathJax.typesetPromise();
                }
            }
        """)
        
        footer_html = """
        <div style="font-family: 'Inter', -apple-system, sans-serif; font-size: 10px; width: 100%; text-align: center; color: #8c959f; padding-bottom: 5px;">
            Page <span class="pageNumber"></span> of <span class="totalPages"></span>
        </div>
        """
        
        await page.pdf(
            path=output_pdf_path, 
            print_background=True,
            display_header_footer=True,
            header_template="<div></div>",
            footer_template=footer_html,
            margin={"top": "0px", "bottom": "0px", "left": "0px", "right": "0px"}
        )
    finally:
        await page.close()
        if os.path.exists(temp_html_path):
            os.remove(temp_html_path)
        gc.collect()

def get_settings_keyboard(chat_id):
    orientation = get_user_setting(chat_id, "orientation", "portrait")
    compact = get_user_setting(chat_id, "compact", False)
    columns = get_user_setting(chat_id, "columns", 1)
    
    orient_btn = "📑 جهت: افقی" if orientation == "landscape" else "📄 جهت: عمودی"
    compact_btn = "📦 حالت: فشرده" if compact else "📖 حالت: عادی"
    col_btn = "📰 ستون: دو ستونی" if columns == 2 else "📃 ستون: تک ستونی"
    
    keyboard = [
        [InlineKeyboardButton(orient_btn, callback_data="toggle_orient"),
         InlineKeyboardButton(compact_btn, callback_data="toggle_compact")],
        [InlineKeyboardButton(col_btn, callback_data="toggle_cols")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    reply_markup = get_settings_keyboard(chat_id)
    
    text = (
        "سلام! 👋\n\n"
        "📄 فایل `.md`/`.txt`، متن دلخواه و یا فایل فشرده `.zip` خود را بفرستید.\n"
        "💡 نکته: در فایل‌های ZIP، نام فایل PDF خروجی دقیقا مطابق با نام فایل مارک‌داون متناظر (یا هشتگ داخلی آن) خواهد بود.\n\n"
        "⚙️ تنظیمات خروجی خود را از طریق دکمه‌های زیر مدیریت کنید:"
    )
    
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
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
        
    await start(update, context)

async def process_conversion(update: Update, context: ContextTypes.DEFAULT_TYPE, md_text: str, file_default_name=None):
    chat_id = update.effective_chat.id
    orientation = get_user_setting(chat_id, "orientation", "portrait")
    compact = get_user_setting(chat_id, "compact", False)
    columns = get_user_setting(chat_id, "columns", 1)
    
    default_name = file_default_name if file_default_name else f"Note_{update.message.message_id}"
    file_title, md_text = extract_title_and_hashtag(md_text, default_name=default_name)
    
    if len(md_text) > 5000:
        status_msg = await update.message.reply_text("⚠️ حجم متن بالا است. پردازش چند ثانیه زمان می‌برد...")
    else:
        status_msg = await update.message.reply_text("⏳ در صف پردازش...")
    
    async with conversion_lock:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_msg.message_id,
            text=f"⚙️ در حال تولید فایل `{file_title}.pdf`..."
        )
        
        pdf_path = f"temp_{update.message.message_id}.pdf"
        
        try:
            await generate_pdf_output(md_text, pdf_path, orientation=orientation, compact=compact, columns=columns)
            
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg.message_id,
                text="✅ فایل PDF آماده شد!"
            )
            
            with open(pdf_path, 'rb') as pdf_file:
                await update.message.reply_document(document=pdf_file, filename=f"{file_title}.pdf")
                
        except Exception as e:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg.message_id,
                text=f"❌ خطایی رخ داد: {str(e)}"
            )
        finally:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    filename = doc.file_name.lower()
    
    if not (filename.endswith('.md') or filename.endswith('.txt') or filename.endswith('.zip')):
        await update.message.reply_text("⛔ لطفاً فقط فایل `.md`، `.txt` یا `.zip` بفرستید.")
        return
        
    file = await context.bot.get_file(doc.file_id)
    temp_path = f"dl_{doc.file_id}.tmp"
    await file.download_to_drive(temp_path)
    
    if filename.endswith('.zip'):
        status_msg = await update.message.reply_text("📦 استخراج و پردازش جریانی فایل‌های ZIP...")
        extracted_dir = f"extracted_{doc.file_id}"
        os.makedirs(extracted_dir, exist_ok=True)
        
        pdf_files = []
        try:
            with zipfile.ZipFile(temp_path, 'r') as zip_ref:
                zip_ref.extractall(extracted_dir)
                
            chat_id = update.effective_chat.id
            orient = get_user_setting(chat_id, "orientation", "portrait")
            comp = get_user_setting(chat_id, "compact", False)
            cols = get_user_setting(chat_id, "columns", 1)
            
            for root, dirs, files in os.walk(extracted_dir):
                for file_name in files:
                    if file_name.lower().endswith(('.md', '.txt')):
                        file_path = os.path.join(root, file_name)
                        try:
                            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                content = f.read()
                            
                            # نام پیش‌فرض فایل برابر با نام فایل متناظر داخل زیپ (بدون پسوند)
                            base_name = file_name.rsplit('.', 1)[0]
                            title, clean_content = extract_title_and_hashtag(content, default_name=base_name)
                            
                            out_pdf = os.path.abspath(f"{title}_{os.getpid()}.pdf")
                            
                            async with conversion_lock:
                                await generate_pdf_output(clean_content, out_pdf, orientation=orient, compact=comp, columns=cols)
                                
                            if os.path.exists(out_pdf):
                                pdf_files.append((out_pdf, f"{title}.pdf"))
                        except Exception:
                            continue
                        
            if pdf_files:
                zip_out_name = f"Batch_PDFs_{doc.file_id}.zip"
                with zipfile.ZipFile(zip_out_name, 'w') as zip_out:
                    for pdf_abs_path, pdf_display_name in pdf_files:
                        if os.path.exists(pdf_abs_path):
                            zip_out.write(pdf_abs_path, arcname=pdf_display_name)
                            
                with open(zip_out_name, 'rb') as z_file:
                    await update.message.reply_document(document=z_file, filename="Converted_Files.zip")
                
                if os.path.exists(zip_out_name):
                    os.remove(zip_out_name)
                for pdf_abs_path, _ in pdf_files:
                    if os.path.exists(pdf_abs_path):
                        os.remove(pdf_abs_path)
                        
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=status_msg.message_id)
            else:
                await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text="❌ هیچ فایل `.md` یا `.txt` معتبری داخل فایل ZIP یافت نشد.")
        except Exception as e:
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=status_msg.message_id, text=f"❌ خطا در پردازش فایل ZIP: {str(e)}")
        finally:
            if os.path.exists(extracted_dir):
                import shutil
                shutil.rmtree(extracted_dir)
            gc.collect()
    else:
        with open(temp_path, 'r', encoding='utf-8', errors='ignore') as f:
            md_text = f.read()
        base_name = doc.file_name.rsplit('.', 1)[0]
        await process_conversion(update, context, md_text, file_default_name=base_name)
        
    if os.path.exists(temp_path):
        os.remove(temp_path)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text.startswith('/'):
        return
    await process_conversion(update, context, text)

if __name__ == '__main__':
    TOKEN = os.getenv("BOT_TOKEN")
    if not TOKEN:
        print("❌ Error: BOT_TOKEN is missing!")
    else:
        threading.Thread(target=run_dummy_server, daemon=True).start()
        print("✅ Starting Telegram Bot...")
        app = Application.builder().token(TOKEN).build()
        
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CallbackQueryHandler(button_callback))
        
        app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
        
        app.run_polling()

