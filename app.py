import os
from datetime import datetime
import threading
import time
import psycopg

import requests
import telebot
from telebot import types
from flask import Flask, request

# ============ CẤU HÌNH ============

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))

REG_LINK = "https://gg88k.xyz"
WEBAPP_LINK = "https://gg88k.xyz"

ENABLE_KEEP_ALIVE = os.getenv("ENABLE_KEEP_ALIVE", "false").lower() == "true"
PING_URL = os.getenv("PING_URL")
PING_INTERVAL = int(os.getenv("PING_INTERVAL", "300"))

# ============ KHỞI TẠO ============

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
server = Flask(__name__)

user_state = {}
debug_get_id_mode = set()
admin_state = {}

DATABASE_URL = os.getenv("DATABASE_URL")


# ============ DB ============

def db_conn():
    return psycopg.connect(DATABASE_URL, connect_timeout=10)


def init_db():
    if not DATABASE_URL:
        print("⚠️ DATABASE_URL chưa có, bot vẫn chạy nhưng không lưu user vào DB.")
        return

    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    chat_id BIGINT PRIMARY KEY,
                    first_seen TIMESTAMP DEFAULT NOW(),
                    last_seen TIMESTAMP DEFAULT NOW()
                )
            """)
        conn.commit()


def upsert_user(chat_id: int):
    if not DATABASE_URL:
        return
    try:
        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO users(chat_id)
                    VALUES (%s)
                    ON CONFLICT (chat_id)
                    DO UPDATE SET last_seen = NOW()
                """, (chat_id,))
            conn.commit()
    except Exception as e:
        print("Lỗi upsert_user:", e)


def count_users():
    if not DATABASE_URL:
        return 0
    try:
        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM users")
                return cur.fetchone()[0]
    except Exception as e:
        print("Lỗi count_users:", e)
        return 0


def get_all_users():
    if not DATABASE_URL:
        return []
    try:
        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT chat_id FROM users")
                return [row[0] for row in cur.fetchall()]
    except Exception as e:
        print("Lỗi get_all_users:", e)
        return []


def is_admin(chat_id: int) -> bool:
    return chat_id == ADMIN_CHAT_ID


try:
    init_db()
    if DATABASE_URL:
        print("✅ Postgres users table ready.")
except Exception as e:
    print("❌ Lỗi init DB:", e)


# ============ KEEP ALIVE ============

def keep_alive():
    if not PING_URL:
        print("[KEEP_ALIVE] PING_URL chưa cấu hình, không bật keep-alive.")
        return

    print(f"[KEEP_ALIVE] Bắt đầu ping {PING_URL} mỗi {PING_INTERVAL}s")
    while True:
        try:
            r = requests.get(PING_URL, timeout=10)
            print(f"[KEEP_ALIVE] Ping {PING_URL} -> {r.status_code}")
        except Exception as e:
            print("[KEEP_ALIVE] Lỗi ping:", e)
        time.sleep(PING_INTERVAL)


if ENABLE_KEEP_ALIVE:
    threading.Thread(target=keep_alive, daemon=True).start()


# ============ HÀM PHỤ ============

def safe_send_admin_message(text):
    if not ADMIN_CHAT_ID:
        print("⚠️ ADMIN_CHAT_ID chưa cấu hình.")
        return False
    try:
        bot.send_message(ADMIN_CHAT_ID, text)
        return True
    except Exception as e:
        print("Lỗi gửi admin message:", e)
        return False


def safe_forward_to_admin(from_chat_id, message_id):
    if not ADMIN_CHAT_ID:
        print("⚠️ ADMIN_CHAT_ID chưa cấu hình.")
        return False
    try:
        bot.forward_message(ADMIN_CHAT_ID, from_chat_id, message_id)
        return True
    except Exception as e:
        print("Lỗi forward admin:", e)
        return False


def safe_send_admin_photo(photo_file_id, caption):
    if not ADMIN_CHAT_ID:
        print("⚠️ ADMIN_CHAT_ID chưa cấu hình.")
        return False
    try:
        bot.send_photo(ADMIN_CHAT_ID, photo_file_id, caption=caption)
        return True
    except Exception as e:
        print("Lỗi gửi admin photo:", e)
        return False


# ============ DEBUG ============

@bot.message_handler(commands=['myid'])
def myid(message):
    bot.reply_to(message, f"🆔 Chat ID của bạn là: `{message.chat.id}`", parse_mode="Markdown")


@bot.message_handler(commands=['getid'])
def enable_getid(message):
    chat_id = message.chat.id
    debug_get_id_mode.add(chat_id)
    bot.send_message(
        chat_id,
        "✅ Đã bật chế độ lấy FILE_ID.\n"
        "Gửi ảnh/video/file, bot sẽ trả FILE_ID.\n"
        "Tắt bằng /stopgetid",
        parse_mode="Markdown"
    )


@bot.message_handler(commands=['stopgetid'])
def disable_getid(message):
    chat_id = message.chat.id
    debug_get_id_mode.discard(chat_id)
    bot.send_message(chat_id, "🛑 Đã tắt chế độ lấy FILE_ID.")


# ============ ADMIN ============

@bot.message_handler(commands=["admin"])
def admin_panel(message):
    chat_id = message.chat.id
    if not is_admin(chat_id):
        return bot.send_message(chat_id, "❌ Bạn không có quyền admin.")

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📣 Broadcast", "📊 Stats")
    kb.row("❌ Thoát")
    bot.send_message(chat_id, "🔧 Admin Panel", reply_markup=kb)


@bot.message_handler(func=lambda m: is_admin(m.chat.id) and m.text == "📊 Stats")
def admin_stats(message):
    bot.send_message(message.chat.id, f"👥 Tổng user đã lưu: {count_users()}")


@bot.message_handler(func=lambda m: is_admin(m.chat.id) and m.text == "❌ Thoát")
def admin_exit(message):
    admin_state.pop(message.chat.id, None)
    bot.send_message(message.chat.id, "Đã thoát admin.", reply_markup=types.ReplyKeyboardRemove())


@bot.message_handler(func=lambda m: is_admin(m.chat.id) and m.text == "📣 Broadcast")
def admin_broadcast_start(message):
    chat_id = message.chat.id
    admin_state[chat_id] = {"mode": "BROADCAST_WAIT_MEDIA", "payload": None}
    bot.send_message(
        chat_id,
        "📣 Hãy gửi *nội dung cần broadcast*.\n"
        "✅ Hỗ trợ: *Text / Ảnh / Video* (có thể kèm caption).\n"
        "Hủy: /cancel",
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["cancel"])
def cancel_any(message):
    if is_admin(message.chat.id):
        admin_state.pop(message.chat.id, None)
        bot.send_message(message.chat.id, "✅ Đã hủy.")


def _ask_broadcast_confirm(chat_id: int, preview_text: str):
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ Xác nhận gửi", callback_data="BC_CONFIRM"),
        types.InlineKeyboardButton("❌ Hủy", callback_data="BC_CANCEL")
    )
    bot.send_message(
        chat_id,
        f"Bạn sắp gửi đến *{count_users()}* user.\n\n{preview_text}\n\nXác nhận?",
        parse_mode="Markdown",
        reply_markup=kb
    )


@bot.message_handler(
    func=lambda m: is_admin(m.chat.id) and admin_state.get(m.chat.id, {}).get("mode") == "BROADCAST_WAIT_MEDIA",
    content_types=["text"]
)
def admin_receive_broadcast_text(message):
    chat_id = message.chat.id
    text = message.text.strip()
    admin_state[chat_id]["payload"] = {"type": "text", "text": text}
    _ask_broadcast_confirm(chat_id, f"📝 *Text:*\n{text}")


@bot.message_handler(
    func=lambda m: is_admin(m.chat.id) and admin_state.get(m.chat.id, {}).get("mode") == "BROADCAST_WAIT_MEDIA",
    content_types=["photo"]
)
def admin_receive_broadcast_photo(message):
    chat_id = message.chat.id
    file_id = message.photo[-1].file_id
    caption = (message.caption or "").strip()

    admin_state[chat_id]["payload"] = {"type": "photo", "file_id": file_id, "caption": caption}

    preview = "🖼️ *Ảnh*"
    if caption:
        preview += f"\nCaption:\n{caption}"
    _ask_broadcast_confirm(chat_id, preview)


@bot.message_handler(
    func=lambda m: is_admin(m.chat.id) and admin_state.get(m.chat.id, {}).get("mode") == "BROADCAST_WAIT_MEDIA",
    content_types=["video"]
)
def admin_receive_broadcast_video(message):
    chat_id = message.chat.id
    file_id = message.video.file_id
    caption = (message.caption or "").strip()

    admin_state[chat_id]["payload"] = {"type": "video", "file_id": file_id, "caption": caption}

    preview = "🎬 *Video*"
    if caption:
        preview += f"\nCaption:\n{caption}"
    _ask_broadcast_confirm(chat_id, preview)


@bot.callback_query_handler(func=lambda call: call.data in ["BC_CONFIRM", "BC_CANCEL"])
def admin_broadcast_confirm(call):
    chat_id = call.message.chat.id
    if not is_admin(chat_id):
        return bot.answer_callback_query(call.id, "No permission.")

    if call.data == "BC_CANCEL":
        admin_state.pop(chat_id, None)
        bot.answer_callback_query(call.id, "Đã hủy.")
        return bot.edit_message_text("❌ Đã hủy broadcast.", chat_id, call.message.message_id)

    payload = admin_state.get(chat_id, {}).get("payload")
    admin_state.pop(chat_id, None)

    if not payload:
        bot.answer_callback_query(call.id, "Không có nội dung.")
        return bot.edit_message_text("⚠️ Không có nội dung để gửi.", chat_id, call.message.message_id)

    bot.edit_message_text("⏳ Đang gửi...", chat_id, call.message.message_id)

    users = get_all_users()
    sent, failed = 0, 0

    for uid in users:
        try:
            if payload["type"] == "text":
                bot.send_message(uid, payload["text"], disable_web_page_preview=True)
            elif payload["type"] == "photo":
                bot.send_photo(uid, payload["file_id"], caption=payload.get("caption") or None)
            elif payload["type"] == "video":
                bot.send_video(uid, payload["file_id"], caption=payload.get("caption") or None)
            sent += 1
            time.sleep(0.05)
        except Exception as e:
            print("Lỗi broadcast đến", uid, ":", e)
            failed += 1

    safe_send_admin_message(f"✅ Broadcast xong.\nSent: {sent}\nFailed: {failed}")
    bot.answer_callback_query(call.id, "Đã gửi!")


# ============ FLOW USER ============

def ask_account_status(chat_id):
    text = (
        "👋 Chào anh/chị!\n"
        "Em là Bot hỗ trợ nhận CODE ưu đãi GG88.\n\n"
        "👉 Anh/chị đã có tài khoản chơi GG88 chưa ạ?\n\n"
        "(Chỉ cần bấm nút bên dưới: ĐÃ CÓ hoặc CHƯA CÓ, em hỗ trợ ngay! 😊)"
    )

    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("✅ ĐÃ CÓ TÀI KHOẢN", callback_data="have_account")
    )
    markup.row(
        types.InlineKeyboardButton("🆕 CHƯA CÓ – ĐĂNG KÝ NGAY", callback_data="no_account")
    )

    try:
        bot.send_photo(
            chat_id,
            "AgACAgUAAxkBAAMUabwIZVqf50DY1eD-5y9DpFaa9pMAAqwQaxveZOFVLqsTsxa-eWsBAAMCAAN4AAM6BA",
            caption=text,
            reply_markup=markup
        )
    except Exception as e:
        print("Lỗi gửi ảnh ask_account_status:", e)
        bot.send_message(chat_id, text, reply_markup=markup)

    user_state[chat_id] = None


@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = message.chat.id
    upsert_user(chat_id)
    print(">>> /start from:", chat_id)
    ask_account_status(chat_id)


@bot.callback_query_handler(func=lambda call: call.data in ["no_account", "have_account", "registered_done"])
def callback_handler(call):
    chat_id = call.message.chat.id
    data = call.data
    upsert_user(chat_id)

    print(f">>> CALLBACK: {data} CHAT_ID: {chat_id}")

    try:
        bot.answer_callback_query(call.id)
    except Exception as e:
        print("Lỗi answer_callback_query:", e)

    if data == "no_account":
        text = (
            "Tuyệt vời, em gửi anh/chị link đăng ký nè 👇\n\n"
            f"🔗 Link đăng ký: {REG_LINK}\n\n"
            "Anh/chị đăng ký xong bấm nút bên dưới để em hỗ trợ tiếp nhé."
        )

        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("✅ MÌNH ĐĂNG KÝ XONG RỒI", callback_data="registered_done")
        )

        try:
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
        except Exception as e:
            print("Lỗi edit_message_reply_markup:", e)

        try:
            bot.send_photo(
                chat_id,
                "AgACAgUAAxkBAAMQabwIWhPZedJfLcMjSOU9904jvFMAAqsQaxveZOFVkRQRrHEJqiIBAAMCAAN4AAM6BA",
                caption=text,
                reply_markup=markup
            )
        except Exception as e:
            print("Lỗi gửi ảnh no_account:", e)
            bot.send_message(chat_id, text, reply_markup=markup)

    elif data in ("have_account", "registered_done"):
        ask_for_username(chat_id)


def ask_for_username(chat_id):
    text = (
        "Dạ ok anh/chị ❤️\n\n"
        "Anh/chị vui lòng gửi đúng *tên tài khoản* để em kiểm tra.\n\n"
        "Ví dụ:\n"
        "`GG88VIP`"
    )

    try:
        bot.send_photo(
            chat_id,
            "AgACAgUAAxkBAAMWabwIaQ9JFZovWdYdCZignur7Y-UAAq0QaxveZOFVdmsWbVgd1xIBAAMCAAN4AAM6BA",
            caption=text,
            parse_mode="Markdown"
        )
    except Exception as e:
        print("Lỗi gửi ảnh ask_for_username:", e)
        bot.send_message(chat_id, text, parse_mode="Markdown")

    user_state[chat_id] = "WAITING_USERNAME"
    print(f">>> SET STATE WAITING_USERNAME for {chat_id}")


@bot.message_handler(content_types=['text'])
def handle_text(message):
    chat_id = message.chat.id
    upsert_user(chat_id)

    if is_admin(chat_id) and admin_state.get(chat_id, {}).get("mode") == "BROADCAST_WAIT_MEDIA":
        return

    text = (message.text or "").strip()
    state = user_state.get(chat_id)

    print(">>> TEXT:", text, "STATE:", state, "CHAT_ID:", chat_id)

    if text in ["/start", "/admin", "/cancel", "/getid", "/stopgetid", "/myid"]:
        return

    # --- Nếu user chưa vào đúng flow mà gõ text luôn ---
    if state is None:
        bot.send_message(
            chat_id,
            "⚠️ Anh/chị vui lòng bấm nút bên trên trước giúp em nhé.\n"
            "Nếu chưa thấy nút, anh/chị bấm lại /start để em gửi lại ạ."
        )
        return

    # --- WAITING_GAME ---
    if isinstance(state, dict) and state.get("state") == "WAITING_GAME":
        game_type = text
        try:
            tg_username = f"@{message.from_user.username}" if message.from_user.username else "Không có"
            time_str = datetime.now().strftime("%H:%M:%S %d/%m/%Y")

            caption = (
                "📩 KHÁCH GỬI CHUYỂN KHOẢN + CHỌN TRÒ CHƠI\n\n"
                f"👤 Telegram: {tg_username}\n"
                f"🧾 Tên tài khoản: {state.get('username_game', '(không rõ)')}\n"
                f"🆔 Chat ID: {chat_id}\n"
                f"🎯 Trò chơi: {game_type}\n"
                f"⏰ Thời gian: {time_str}"
            )

            safe_send_admin_photo(state["receipt_file_id"], caption)
            bot.send_message(chat_id, "✅ Em đã nhận đủ thông tin, admin sẽ xử lý cho mình ngay nhé ạ ❤️")
        except Exception as e:
            print("Lỗi WAITING_GAME:", e)
            bot.send_message(chat_id, "⚠️ Em gửi thông tin bị lỗi, mình đợi em 1 chút hoặc nhắn CSKH giúp em nhé ạ.")

        user_state[chat_id] = None
        return

    # --- WAITING_USERNAME ---
    if state == "WAITING_USERNAME":
        username_game = text
        user_state[chat_id] = {"state": "WAITING_RECEIPT", "username_game": username_game}

        tg_username = f"@{message.from_user.username}" if message.from_user.username else "Không có"
        time_str = datetime.now().strftime("%H:%M:%S %d/%m/%Y")

        admin_text = (
            "🔔 Có khách mới gửi tên tài khoản\n\n"
            f"👤 Telegram: {tg_username}\n"
            f"🧾 Tên tài khoản: {username_game}\n"
            f"⏰ Thời gian: {time_str}\n"
            f"🆔 Chat ID: {chat_id}"
        )

        ok1 = safe_send_admin_message(admin_text)
        ok2 = safe_forward_to_admin(chat_id, message.message_id)
        print(">>> SEND ADMIN WAITING_USERNAME:", ok1, ok2)

        reply_text = (
            f"Em đã nhận được tên tài khoản: *{username_game}* ✅\n\n"
            "Mình vào GG88 lên vốn theo mốc để nhận khuyến mãi giúp em nhé.\n\n"
            "Lên thành công mình gửi *ảnh chuyển khoản* để admin cộng điểm trực tiếp vào tài khoản cho mình nhé.\n\n"
            "Trang mới đang auto lên km. Có bất cứ thắc mắc gì nhắn tin trực tiếp cho CSKH GG88 ạ:\n"
            "👉 [Thùy Nhi CSKH GG88](https://t.me/thuynhi247)\n"
        )

        try:
            bot.send_photo(
                chat_id,
                "AgACAgUAAxkBAAMNabwGwy2JojJSdIZX10JeFki1nA0AAqQQaxveZOFVrqBWS9QIKQsBAAMCAAN5AAM6BA",
                caption=reply_text,
                parse_mode="Markdown"
            )
            print(">>> REPLIED USER WAITING_USERNAME OK")
        except Exception as e:
            print("Lỗi gửi ảnh reply_text WAITING_USERNAME:", e)
            try:
                bot.send_message(chat_id, reply_text, parse_mode="Markdown", disable_web_page_preview=True)
                print(">>> REPLIED USER WAITING_USERNAME TEXT FALLBACK OK")
            except Exception as e2:
                print("Lỗi gửi text fallback WAITING_USERNAME:", e2)

        return


@bot.message_handler(content_types=['photo', 'document', 'video'])
def handle_media(message):
    chat_id = message.chat.id
    upsert_user(chat_id)

    if chat_id in debug_get_id_mode:
        if message.content_type == 'photo':
            file_id = message.photo[-1].file_id
            media_type = "ẢNH"
        elif message.content_type == 'video':
            file_id = message.video.file_id
            media_type = "VIDEO"
        else:
            file_id = message.document.file_id
            media_type = "FILE"

        bot.reply_to(message, f"✅ *{media_type} FILE_ID:*\n\n`{file_id}`", parse_mode="Markdown")
        return

    state = user_state.get(chat_id)
    print(f">>> MEDIA: {message.content_type} STATE: {state} CHAT_ID: {chat_id}")

    if not (isinstance(state, dict) and state.get("state") == "WAITING_RECEIPT"):
        bot.send_message(
            chat_id,
            "⚠️ Em chưa yêu cầu ảnh ở bước này ạ. Anh/chị bấm /start để bắt đầu lại giúp em nhé."
        )
        return

    if message.content_type == "photo":
        receipt_file_id = message.photo[-1].file_id
    elif message.content_type == "document":
        receipt_file_id = message.document.file_id
    else:
        bot.send_message(chat_id, "Mình gửi *ảnh chuyển khoản* giúp em nhé ạ.", parse_mode="Markdown")
        return

    username_game = state.get("username_game")

    user_state[chat_id] = {
        "state": "WAITING_GAME",
        "receipt_file_id": receipt_file_id,
        "username_game": username_game
    }

    bot.send_message(
        chat_id,
        "🔔 Dạ mình thường chơi hũ hay bcr hay bóng anh nhỉ?\n"
        "Admin sẽ có những khuyến mãi hot dành riêng cho mình nè!",
        parse_mode="Markdown"
    )
    print(f">>> SET STATE WAITING_GAME for {chat_id}")


# ============ WEBHOOK ============

@server.route("/webhook", methods=['POST'])
def telegram_webhook():
    try:
        json_str = request.get_data().decode("utf-8")
        print("[WEBHOOK RAW]", json_str)
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        print("[WEBHOOK] processed ok")
    except Exception as e:
        print("[WEBHOOK ERROR]", repr(e))
    return "OK", 200


@server.route("/", methods=['GET'])
def home():
    return "Bot is running!", 200


@server.route("/health", methods=['GET'])
def health():
    return "ok", 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    server.run(host="0.0.0.0", port=port)
