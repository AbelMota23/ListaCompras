import os
import time
from datetime import datetime
from dotenv import load_dotenv

import gspread
from google.oauth2.service_account import Credentials

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ForceReply,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ---------- CONFIG ----------
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SHEET_NAME = os.getenv("SHEET_NAME", "ListaCompras")

creds_json = os.getenv("GOOGLE_CREDS_JSON")
if creds_json and not os.path.exists("credenciais.json"):
    with open("credenciais.json", "w", encoding="utf-8") as f:
        f.write(creds_json)

HEADERS = ["id", "item", "done", "added_by", "added_at", "done_by", "done_at"]

WAIT_ITEM = 1  # estado do ConversationHandler [web:871]


def now_str():
    return datetime.now().strftime("%d/%m/%Y %H:%M")


def conectar_google_sheets():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file("credenciais.json", scopes=scopes)
    return gspread.authorize(creds)


def ensure_headers(ws):
    try:
        a1 = ws.acell("A1").value
    except Exception:
        a1 = None

    if (a1 or "").strip().lower() != "id":
        ws.clear()
        ws.append_row(HEADERS)


def get_ws():
    gc = conectar_google_sheets()
    sh = gc.open(SHEET_NAME)
    ws = sh.sheet1
    ensure_headers(ws)
    return ws


def mark_done_batch(ws, target_row: int, user_id: int):
    ws.batch_update([
        {"range": f"C{target_row}", "values": [["TRUE"]]},
        {"range": f"F{target_row}", "values": [[str(user_id)]]},
        {"range": f"G{target_row}", "values": [[now_str()]]},
    ])


def add_to_sheet(item: str, user_id: int):
    ws = get_ws()
    new_id = int(time.time() * 1000)
    ws.append_row([new_id, item, "FALSE", str(user_id), now_str(), "", ""])


def main_keyboard():
    # Teclado “normal” com botões (mais rápido que escrever comandos) [web:876]
    return ReplyKeyboardMarkup(
        [["➕ Adicionar", "📋 Lista"]],
        resize_keyboard=True,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛒 Lista de compras\n"
        "Clica em “➕ Adicionar” para inserir itens sem escrever /add.\n"
        "Ou usa /add leite como antes.",
        reply_markup=main_keyboard(),
    )


# -------- NOVO: fluxo de adicionar por botão --------
async def add_begin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Escreve o item a adicionar:",
        reply_markup=ForceReply(selective=True, input_field_placeholder="Ex: leite"),  # [web:878]
    )
    return WAIT_ITEM


async def add_receive_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    item = (update.message.text or "").strip()
    if not item or item in ("➕ Adicionar", "📋 Lista"):
        await update.message.reply_text("Envia só o nome do item (ex: leite).")
        return WAIT_ITEM

    user = update.effective_user
    add_to_sheet(item, user.id)
    await update.message.reply_text(f"✅ Adicionado: {item}", reply_markup=main_keyboard())
    return ConversationHandler.END  # [web:871]


async def cancel_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelado.", reply_markup=main_keyboard())
    return ConversationHandler.END  # [web:871]


# -------- mantém /add leite (rápido) --------
async def add_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        # Se /add sem args, entra no fluxo (igual ao botão)
        return await add_begin(update, context)

    item = " ".join(context.args).strip()
    user = update.effective_user
    add_to_sheet(item, user.id)
    await update.message.reply_text(f"✅ Adicionado: {item}", reply_markup=main_keyboard())
    return ConversationHandler.END


def build_list_message_and_keyboard(ws):
    rows = ws.get_all_values()
    if len(rows) <= 1:
        return "Lista vazia.", None

    pending = []
    for r in rows[1:]:
        if len(r) >= 3 and str(r[2]).upper() != "TRUE":
            pending.append((str(r[0]), r[1]))

    if not pending:
        return "✅ Nada pendente.", None

    lines = ["🛒 O que falta comprar:"]
    keyboard = []

    for item_id, item_name in pending:
        lines.append(f"- {item_name}")

        short = item_name.strip()
        if len(short) > 30:
            short = short[:27] + "..."

        keyboard.append([
            InlineKeyboardButton(f"✅ {short}", callback_data=f"done:{item_id}")
        ])

    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


async def list_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ws = get_ws()
    text, markup = build_list_message_and_keyboard(ws)
    if markup:
        await update.message.reply_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    if not data.startswith("done:"):
        return

    item_id = data.split(":", 1)[1]
    user = update.effective_user

    ws = get_ws()
    rows = ws.get_all_values()

    target_row = None
    for idx, r in enumerate(rows[1:], start=2):
        if len(r) >= 1 and str(r[0]) == str(item_id):
            target_row = idx
            break

    if not target_row:
        await query.edit_message_text("❌ Item não encontrado (talvez já foi marcado).")
        return

    mark_done_batch(ws, target_row, user.id)

    text, markup = build_list_message_and_keyboard(ws)
    if markup:
        await query.edit_message_text(text, reply_markup=markup)
    else:
        await query.edit_message_text(text)


def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("Falta TELEGRAM_TOKEN")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    add_conv = ConversationHandler(  # [web:871]
        entry_points=[
            CommandHandler("add", add_item),
            MessageHandler(filters.Regex(r"^➕ Adicionar$"), add_begin),
        ],
        states={
            WAIT_ITEM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_receive_item),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_add),
            MessageHandler(filters.Regex(r"^/cancel$"), cancel_add),
        ],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex(r"^📋 Lista$"), list_items))
    app.add_handler(CommandHandler("list", list_items))
    app.add_handler(add_conv)
    app.add_handler(CallbackQueryHandler(callback_handler))

    print("🤖 Bot lista compras a correr")
    app.run_polling()


if __name__ == "__main__":
    main()





