import os
from datetime import datetime
from dotenv import load_dotenv

import gspread
from google.oauth2.service_account import Credentials

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ---------- CONFIG ----------
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SHEET_NAME = os.getenv("SHEET_NAME", "ListaCompras")  # nome exato do ficheiro Google Sheets

# Cria credenciais.json a partir da variável (multiline no Railway)
creds_json = os.getenv("GOOGLE_CREDS_JSON")
if creds_json and not os.path.exists("credenciais.json"):
    with open("credenciais.json", "w", encoding="utf-8") as f:
        f.write(creds_json)

HEADERS = ["id", "item", "done", "added_by", "added_at", "done_by", "done_at"]

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
    ws = sh.sheet1  # 1ª aba
    ensure_headers(ws)
    return ws

def parse_id(x: str) -> int:
    try:
        return int(str(x).strip())
    except Exception:
        return 0

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛒 Lista de compras\n"
        "Adicionar: /add leite\n"
        "Ver lista: /list\n"
        "Marcar comprado: botão ✅"
    )

async def add_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /add <item> (ex: /add leite)")
        return

    item = " ".join(context.args).strip()
    user = update.effective_user

    ws = get_ws()
    rows = ws.get_all_values()

    last_id = 0
    if len(rows) > 1:
        last_id = max(parse_id(r[0]) for r in rows[1:] if r)
    new_id = last_id + 1

    ws.append_row([new_id, item, "FALSE", str(user.id), now_str(), "", ""])
    await update.message.reply_text(f"✅ Adicionado: {item}")

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
    for idx, r in enumerate(rows[1:], start=2):  # start=2 porque linha 1 é header
        if len(r) >= 1 and str(r[0]) == str(item_id):
            target_row = idx
            break

    if not target_row:
        await query.edit_message_text("❌ Item não encontrado (talvez já foi marcado).")
        return

    ws.update_cell(target_row, 3, "TRUE")
    ws.update_cell(target_row, 6, str(user.id))
    ws.update_cell(target_row, 7, now_str())

    text, markup = build_list_message_and_keyboard(ws)
    if markup:
        await query.edit_message_text(text, reply_markup=markup)
    else:
        await query.edit_message_text(text)

def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("Falta TELEGRAM_TOKEN")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_item))
    app.add_handler(CommandHandler("list", list_items))
    app.add_handler(CallbackQueryHandler(callback_handler))

    print("🤖 Bot lista compras a correr")
    app.run_polling()  # mantém o bot ligado [web:627][web:633]

if __name__ == "__main__":
    main()

