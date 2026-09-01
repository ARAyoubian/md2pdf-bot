import os
import re
import tempfile
import markdown
import threading
import asyncio
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
user_orientations = {}  
user_compact_modes = {} 

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
            padding: 4px 18px;
            color: var(--text-muted);
            border-inline-start: 4px solid var(--accent-color);
            background: var(--bg-code);
            border-radius: 0 6px 6px 0;
        }

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

        /* استایل‌های پیشرفته برای رندر روان فرمول‌ها در جداول و لیست‌ها */
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
    
    <!-- تنظیمات پیشرفته و بهینه‌شده MathJax برای جداول، لیست‌ها و بلوک‌های چندخطی -->
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

def extract_title_and_hashtag(text, default_name="Document"):
    # استخراج هشتگ به عنوان نام فایل خروجی (مثلاً #فصل_اول)
    hashtag_match = re.search(r'#([رعشگپتثجحخدذرزسشصطظعغفقکلمنوهیژآإأؤةءچپگژ۱۲۳۴۵۶۷۸۹۰a-zA-Z0-9_]+)', text)
    if hashtag_match:
        tag_name = hashtag_match.group(1).strip()
        if tag_name:
            # حذف هشتگ از متن اصلی تا داخل PDF چاپ نشود
            clean_text = text.replace(f"#{tag_name}", "").strip()
            return tag_name, clean_text

    # استخراج اولین هدینگ سند
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
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
        )
        print("✅ Global Browser Instance Initialized.")

async def generate_pdf_output(md_text, output_pdf_path, orientation="portrait", compact=False):
    await init_browser()
    
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

def get_settings_keyboard(chat_id):
    orientation = user_orientations.get(chat_id, "portrait")
    compact = user_compact_modes.get(chat_id, False)
    
    orient_btn = "📑 جهت: افقی" if orientation == "landscape" else "📄 جهت: عمودی"
    compact_btn = "📦 حالت: فشرده" if compact else "📖 حالت: عادی"
    
    keyboard = [
        [InlineKeyboardButton(orient_btn, callback_data="toggle_orient"),
         InlineKeyboardButton(compact_btn, callback_data="toggle_compact")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    reply_markup = get_settings_keyboard(chat_id)
    
    text = (
        "سلام! 👋\n\n"
        "📄 فایل `.md`/`.txt` یا متن دلخواهتان را بفرستید تا فوراً به PDF تبدیل شود.\n"
        "💡 نکته: برای نام‌گذاری سفارشی فایل خروجی، کافیست یک هشتگ مثل `#فصل_اول` در متن بگذارید.\n\n"
        "⚙️ تنظیمات خروجی خود را از طریق دکمه‌های زیر تغییر دهید:"
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
        current = user_orientations.get(chat_id, "portrait")
        user_orientations[chat_id] = "landscape" if current == "portrait" else "portrait"
    elif data == "toggle_compact":
        current = user_compact_modes.get(chat_id, False)
        user_compact_modes[chat_id] = not current
        
    await start(update, context)

async def process_conversion(update: Update, context: ContextTypes.DEFAULT_TYPE, md_text: str):
    chat_id = update.effective_chat.id
    orientation = user_orientations.get(chat_id, "portrait")
    compact = user_compact_modes.get(chat_id, False)
    
    # استخراج هوشمند نام فایل از هشتگ یا هدینگ
    file_title, md_text = extract_title_and_hashtag(md_text, default_name=f"Note_{update.message.message_id}")
    
    # هشدار هوشمند برای فایل‌ها و متن‌های حجیم
    if len(md_text) > 5000:
        status_msg = await update.message.reply_text("⚠️ متن یا فایل شما حجیم است. پردازش ممکن است چند ثانیه بیشتر طول بکشد، لطفاً صبور باشید...")
    else:
        status_msg = await update.message.reply_text("⏳ در صف پردازش...")
    
    async with conversion_lock:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_msg.message_id,
            text=f"⚙️ در حال رندر فرمول‌های ریاضی و تولید فایل `{file_title}.pdf`..."
        )
        
        pdf_path = f"temp_{update.message.message_id}.pdf"
        
        try:
            await generate_pdf_output(md_text, pdf_path, orientation=orientation, compact=compact)
            
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
    if not (filename.endswith('.md') or filename.endswith('.txt')):
        await update.message.reply_text("⛔ لطفاً فقط فایل `.md` یا `.txt` بفرستید.")
        return
        
    file = await context.bot.get_file(doc.file_id)
    temp_path = f"dl_{doc.file_id}.tmp"
    await file.download_to_drive(temp_path)
    
    with open(temp_path, 'r', encoding='utf-8') as f:
        md_text = f.read()
    os.remove(temp_path)
    
    await process_conversion(update, context, md_text)

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

