#!/usr/bin/env python3
"""
Telegram Bot — Prompt Generator for Image + Video + Voice
==========================================================
Flow: /start → paste content → select #scenes → select style → select model → receive .txt

Independent bot. Run with: python telegram_bot.py
Requires: TELEGRAM_BOT_TOKEN in .env (separate bot from trading bot)
"""

import os
import sys
import io
import json
import logging
import threading
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask

# Load env from same directory (local) or os.environ (Render)
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup,
    ReplyKeyboardRemove, KeyboardButton,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes,
)

from styles import STYLES, SCENE_OPTIONS, MODEL_OPTIONS
from prompt_generator import generate, Script

# ============================================================
# Logging
# ============================================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("prompt-bot")

# ============================================================
# Conversation States
# ============================================================
WAITING_CONTENT = 1
WAITING_SCENES = 2
WAITING_STYLE = 3
WAITING_MODEL = 4
WAITING_CUSTOM_STYLE = 5

# ============================================================
# Authorization (Whitelist)
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUTHORIZED_FILE = os.path.join(BASE_DIR, "authorized.json")

def _load_json(path, default):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def _save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def get_owner_ids() -> list[int]:
    """Get admin chat IDs from env var ALLOWED_USER_IDS (comma-separated)."""
    raw = os.environ.get("ALLOWED_USER_IDS", "")
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            ids.append(int(part))
    return ids

def load_authorized() -> set:
    """Load full authorized user set (owners + runtime-added)."""
    owners = set(get_owner_ids())
    runtime = set(_load_json(AUTHORIZED_FILE, {}).get("users", []))
    return owners | runtime

def save_authorized(users: set):
    owners = set(get_owner_ids())
    runtime_only = list(users - owners)
    _save_json(AUTHORIZED_FILE, {"users": runtime_only})

def is_authorized(chat_id: int) -> bool:
    return chat_id in load_authorized()

def authorize_user(chat_id: int) -> bool:
    authorized = load_authorized()
    if chat_id in authorized:
        return False
    authorized.add(chat_id)
    save_authorized(authorized)
    return True

def deauthorize_user(chat_id: int) -> bool:
    authorized = load_authorized()
    owners = set(get_owner_ids())
    if chat_id not in authorized or chat_id in owners:
        return False
    authorized.discard(chat_id)
    save_authorized(authorized)
    return True

# ============================================================
# User session data (in-memory, resets on restart)
# ============================================================
user_sessions = {}

# ============================================================
# Helpers
# ============================================================
def build_style_keyboard(include_custom: bool = True) -> InlineKeyboardMarkup:
    """Build inline keyboard for style selection, 2 per row."""
    buttons = []
    for key, info in STYLES.items():
        buttons.append([InlineKeyboardButton(info["label"], callback_data=f"style_{key}")])
    if include_custom:
        buttons.append([InlineKeyboardButton("✏️ Custom (tự nhập style)...", callback_data="style_custom")])
    return InlineKeyboardMarkup(buttons)


def build_scene_keyboard() -> InlineKeyboardMarkup:
    """Build inline keyboard for scene count."""
    buttons = []
    row = []
    for i, n in enumerate(SCENE_OPTIONS):
        row.append(InlineKeyboardButton(str(n), callback_data=f"scenes_{n}"))
        if len(row) == 3 or i == len(SCENE_OPTIONS) - 1:
            buttons.append(row)
            row = []
    buttons.append([InlineKeyboardButton("✏️ Nhập số khác...", callback_data="scenes_custom")])
    return InlineKeyboardMarkup(buttons)


def build_model_keyboard() -> InlineKeyboardMarkup:
    """Build inline keyboard for model selection."""
    buttons = []
    for key, label in MODEL_OPTIONS.items():
        buttons.append([InlineKeyboardButton(label, callback_data=f"model_{key}")])
    return InlineKeyboardMarkup(buttons)


def get_user_session(user_id: int) -> dict:
    if user_id not in user_sessions:
        user_sessions[user_id] = {}
    return user_sessions[user_id]

# ============================================================
# Command Handlers
# ============================================================
UNAUTHORIZED_MSG = (
    "🔒 Bot này là hệ thống cá nhân, chỉ dành cho người được ủy quyền.\n\n"
    "Nếu bạn nghĩ mình cần quyền truy cập, hãy liên hệ quản trị viên.\n"
    "Xin cảm ơn! 🙏"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /start — begin the prompt generation flow."""
    user = update.effective_user
    user_id = user.id
    chat_id = update.effective_chat.id

    # Authorization check
    if not is_authorized(chat_id):
        await update.message.reply_text(UNAUTHORIZED_MSG)
        return ConversationHandler.END

    user_sessions[user_id] = {}  # Reset session

    welcome = f"""🪐 *Carmen Prompt Generator* 

Chào {user.first_name}! 

Bot này giúp cậu tạo *hàng loạt prompt* cho ảnh + video + lời thoại từ nội dung cậu cung cấp.

📋 *Cách dùng:*
1. Paste nội dung kịch bản / ý tưởng
2. Chọn số lượng phân cảnh
3. Chọn style (người que, 3D, cổ trang, ASMR...)
4. Chọn AI model (Gemini hoặc DeepSeek)
5. Nhận file .txt gồm prompt ảnh, video, lời thoại

👇 Bắt đầu bằng cách *paste nội dung* của cậu xuống đây:
(Ví dụ: "Một câu chuyện về chàng trai khởi nghiệp thất bại 3 lần, lần thứ 4 thành công nhờ bài học từ thất bại")"""

    await update.message.reply_text(welcome, parse_mode="Markdown")
    return WAITING_CONTENT


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel — abort flow."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if not is_authorized(chat_id):
        await update.message.reply_text(UNAUTHORIZED_MSG)
        return ConversationHandler.END

    user_sessions.pop(user_id, None)
    await update.message.reply_text(
        "❌ Đã huỷ. Gửi /start để bắt đầu lại.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help."""
    await update.message.reply_text(
        "🪐 *Carmen Prompt Generator*\n\n"
        "Lệnh:\n"
        "/start — Tạo kịch bản mới\n"
        "/cancel — Huỷ flow hiện tại\n"
        "/help — Hiển thị trợ giúp này\n\n"
        "Bot tạo prompt ảnh (Banana/Imagen) + video (Veo) + lời thoại từ nội dung của cậu.",
        parse_mode="Markdown",
    )


# ── Admin Commands ──

async def adduser(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /adduser — add a user to whitelist (owner only)."""
    chat_id = update.effective_chat.id

    if chat_id not in get_owner_ids():
        await update.message.reply_text("🔒 Bạn không có quyền thực hiện lệnh này.")
        return

    parts = update.message.text.split()
    if len(parts) < 2:
        await update.message.reply_text("⚠️ Cú pháp: /adduser <chat_id>\n\nVí dụ: /adduser 123456789")
        return

    try:
        target_id = int(parts[1])
    except ValueError:
        await update.message.reply_text("❌ Chat ID không hợp lệ.")
        return

    if authorize_user(target_id):
        await update.message.reply_text(f"✅ Đã thêm user `{target_id}` vào danh sách được ủy quyền.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"ℹ️ User `{target_id}` đã có trong danh sách.", parse_mode="Markdown")


async def removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /removeuser — remove a user from whitelist (owner only)."""
    chat_id = update.effective_chat.id

    if chat_id not in get_owner_ids():
        await update.message.reply_text("🔒 Bạn không có quyền thực hiện lệnh này.")
        return

    parts = update.message.text.split()
    if len(parts) < 2:
        await update.message.reply_text("⚠️ Cú pháp: /removeuser <chat_id>")
        return

    try:
        target_id = int(parts[1])
    except ValueError:
        await update.message.reply_text("❌ Chat ID không hợp lệ.")
        return

    if deauthorize_user(target_id):
        await update.message.reply_text(f"✅ Đã xóa user `{target_id}` khỏi danh sách.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ Không thể xóa. User `{target_id}` không tồn tại hoặc là chủ sở hữu.", parse_mode="Markdown")


async def whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /whitelist — show authorized users."""
    chat_id = update.effective_chat.id

    if not is_authorized(chat_id):
        return

    authorized = load_authorized()
    owners = set(get_owner_ids())
    runtime = authorized - owners

    lines = ["👥 *Danh sách ủy quyền:*\n"]
    lines.append(f"👑 Chủ sở hữu ({len(owners)}):")
    for oid in owners:
        lines.append(f"  • `{oid}`")
    if runtime:
        lines.append(f"\n📋 User được thêm ({len(runtime)}):")
        for rid in sorted(runtime):
            lines.append(f"  • `{rid}`")
    else:
        lines.append("\n(không có user nào được thêm thủ công)")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

# ============================================================
# State 1: Receive Content
# ============================================================
async def receive_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive user content and ask for number of scenes."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # Re-check authorization at each state
    if not is_authorized(chat_id):
        await update.message.reply_text(UNAUTHORIZED_MSG)
        return ConversationHandler.END

    session = get_user_session(user_id)
    session["content"] = update.message.text

    await update.message.reply_text(
        f"✅ Đã nhận nội dung ({len(session['content'])} ký tự)\n\n"
        "🎬 *Chọn số lượng phân cảnh:*",
        parse_mode="Markdown",
        reply_markup=build_scene_keyboard(),
    )
    return WAITING_SCENES


# ============================================================
# State 2: Receive Scene Count
# ============================================================
async def receive_scenes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle scene count selection via inline buttons."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat.id

    if not is_authorized(chat_id):
        await query.edit_message_text(UNAUTHORIZED_MSG)
        return ConversationHandler.END

    session = get_user_session(user_id)

    data = query.data
    if data == "scenes_custom":
        await query.edit_message_text(
            "✏️ Nhập số phân cảnh cậu muốn (số nguyên, ví dụ: 8):",
        )
        return WAITING_SCENES
    else:
        num = int(data.replace("scenes_", ""))
        session["num_scenes"] = num
        await query.edit_message_text(
            f"✅ Số phân cảnh: *{num}*\n\n"
            "🎨 *Chọn style hình ảnh:*",
            parse_mode="Markdown",
            reply_markup=build_style_keyboard(),
        )
        return WAITING_STYLE


async def receive_scenes_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle custom scene count via text."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if not is_authorized(chat_id):
        await update.message.reply_text(UNAUTHORIZED_MSG)
        return ConversationHandler.END

    session = get_user_session(user_id)

    try:
        num = int(update.message.text.strip())
        if num < 1:
            raise ValueError
        if num > 30:
            await update.message.reply_text("⚠️ Tối đa 30 phân cảnh. Vui lòng nhập số từ 1-30:")
            return WAITING_SCENES
    except ValueError:
        await update.message.reply_text("⚠️ Vui lòng nhập một số nguyên hợp lệ (ví dụ: 8):")
        return WAITING_SCENES

    session["num_scenes"] = num
    await update.message.reply_text(
        f"✅ Số phân cảnh: *{num}*\n\n"
        "🎨 *Chọn style hình ảnh:*",
        parse_mode="Markdown",
        reply_markup=build_style_keyboard(),
    )
    return WAITING_STYLE


# ============================================================
# State 3: Receive Style
# ============================================================
async def receive_style_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle style selection via inline buttons."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat.id

    if not is_authorized(chat_id):
        await query.edit_message_text(UNAUTHORIZED_MSG)
        return ConversationHandler.END

    session = get_user_session(user_id)

    data = query.data
    if data == "style_custom":
        # List available styles for reference
        style_list = "\n".join([f"• {info['label']}" for info in STYLES.values()])
        await query.edit_message_text(
            f"Các style có sẵn:\n{style_list}\n\n"
            "✏️ *Nhập mô tả style cậu muốn* (bằng tiếng Việt hoặc tiếng Anh):\n"
            "Ví dụ: 'Phong cách cyberpunk neon, Tokyo 2077, mưa, đèn LED'",
            parse_mode="Markdown",
        )
        return WAITING_CUSTOM_STYLE
    else:
        style_key = data.replace("style_", "")
        session["style"] = style_key
        style_label = STYLES[style_key]["label"]
        await query.edit_message_text(
            f"✅ Style: *{style_label}*\n\n"
            "🤖 *Chọn AI model để tạo prompt:*",
            parse_mode="Markdown",
            reply_markup=build_model_keyboard(),
        )
        return WAITING_MODEL


async def receive_custom_style(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle custom style text input."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if not is_authorized(chat_id):
        await update.message.reply_text(UNAUTHORIZED_MSG)
        return ConversationHandler.END

    session = get_user_session(user_id)
    session["custom_style"] = update.message.text

    await update.message.reply_text(
        f"✅ Style custom: *{session['custom_style']}*\n\n"
        "🤖 *Chọn AI model để tạo prompt:*",
        parse_mode="Markdown",
        reply_markup=build_model_keyboard(),
    )
    return WAITING_MODEL


# ============================================================
# State 4: Receive Model & Generate
# ============================================================
async def receive_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle model selection, generate, and send result."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat.id

    if not is_authorized(chat_id):
        await query.edit_message_text(UNAUTHORIZED_MSG)
        return ConversationHandler.END

    session = get_user_session(user_id)

    model_key = query.data.replace("model_", "")
    session["model"] = model_key
    model_label = MODEL_OPTIONS[model_key]

    # Build status message
    style_key = session.get("style", "custom")
    if style_key == "custom" or style_key not in STYLES:
        style_label = session.get("custom_style", "Custom")
    else:
        style_label = STYLES[style_key]["label"]

    await query.edit_message_text(
        f"🪐 *Đang tạo kịch bản...*\n\n"
        f"• Nội dung: {len(session['content'])} ký tự\n"
        f"• Phân cảnh: {session['num_scenes']}\n"
        f"• Style: {style_label}\n"
        f"• Model: {model_label}\n\n"
        f"⏳ Vui lòng đợi...",
        parse_mode="Markdown",
    )

    # Generate
    try:
        script = generate(
            content=session["content"],
            num_scenes=session["num_scenes"],
            style_key=style_key if style_key in STYLES else "cinematic",
            model=model_key,
        )

        # Override style label for custom
        if style_key not in STYLES:
            script.style = session.get("custom_style", "custom")

        # Generate TXT
        txt_content = script.to_txt()

        # Build preview
        preview = f"✅ *Hoàn thành!* — {script.num_scenes} phân cảnh\n\n"
        preview += f"📝 *{script.title}*\n\n"
        for s in script.scenes[:3]:
            preview += f"🎬 *Cảnh {s.scene_number}:* _{s.dialogue[:80]}..._\n"
        if script.num_scenes > 3:
            preview += f"\n_...và {script.num_scenes - 3} cảnh nữa_"

        # Send as file
        filename = f"kichban_{script.title.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
        file_bytes = io.BytesIO(txt_content.encode("utf-8"))
        file_bytes.name = filename

        await query.message.reply_document(
            document=file_bytes,
            filename=filename,
            caption=preview,
            parse_mode="Markdown",
        )

        # Suggest next action
        await query.message.reply_text(
            "🔄 Muốn tạo kịch bản khác? Gửi /start\n"
            "📋 Hoặc paste nội dung mới ngay bên dưới để tạo tiếp.",
        )

    except ValueError as e:
        await query.message.reply_text(
            f"⚠️ *Lỗi API Key:* {str(e)[:200]}\n\n"
            "Kiểm tra GEMINI_API_KEY hoặc DEEPSEEK_API_KEY trong file .env",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Generation error: {e}", exc_info=True)
        await query.message.reply_text(
            f"❌ *Lỗi khi tạo:* {str(e)[:300]}\n\n"
            "Thử lại với model khác hoặc nội dung ngắn hơn. /start để làm lại.",
            parse_mode="Markdown",
        )

    return ConversationHandler.END


# ============================================================
# Flask Health Server (for Render free tier port binding)
# ============================================================
health_app = Flask(__name__)

@health_app.route("/health")
def health():
    return "OK", 200

@health_app.route("/")
def index():
    return "🪐 Carmen Prompt Generator Bot is running.", 200


def _start_health_server():
    """Start minimal Flask server so Render detects an open port."""
    port = int(os.getenv("PORT", "10000"))
    logger.info(f"💓 Health server on port {port}")
    health_app.run(host="0.0.0.0", port=port, use_reloader=False)


# ============================================================
# Main
# ============================================================
def main():
    token = os.getenv("PROMPT_BOT_TOKEN")
    if not token:
        print("❌ PROMPT_BOT_TOKEN not found in .env")
        print("Vui lòng thêm PROMPT_BOT_TOKEN vào .env")
        print("Tạo bot mới tại @BotFather trên Telegram")
        sys.exit(1)

    # Start health server in background thread (Render needs an open port)
    threading.Thread(target=_start_health_server, daemon=True).start()

    # Build conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_CONTENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_content),
            ],
            WAITING_SCENES: [
                CallbackQueryHandler(receive_scenes_callback, pattern="^scenes_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_scenes_text),
            ],
            WAITING_STYLE: [
                CallbackQueryHandler(receive_style_callback, pattern="^style_"),
            ],
            WAITING_CUSTOM_STYLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_custom_style),
            ],
            WAITING_MODEL: [
                CallbackQueryHandler(receive_model, pattern="^model_"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
        per_user=True,
        per_chat=True,
    )

    # Build app
    app = Application.builder().token(token).build()
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("help", help_cmd))
    # Admin commands
    app.add_handler(CommandHandler("adduser", adduser))
    app.add_handler(CommandHandler("removeuser", removeuser))
    app.add_handler(CommandHandler("whitelist", whitelist))

    logger.info("🚀 Prompt Generator Bot starting...")
    print("🪐 Carmen Prompt Generator Bot is running...")
    print("   Gửi /start trong Telegram để bắt đầu.")

    # Polling mode (main thread)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
