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
SHEET_NAME = "ListaCompras"  # nome exato da tua planilha
GROUP_ID = int(os.getenv("GROUP_ID", "0"))

# Cria credenciais.json a partir da variável do Railway (multiline é suportado). [web:233]
creds_json = os.getenv("GOOGLE_CREDS_JSON")
if creds_json and not os.path.exists("credenciais.json"):
    with open("credenciais.json", "w", encoding="utf-8") as f:
        f.write(creds_json)

def now_str():
    return datetime.now().strftime("%d/%m/%Y %H:%M")

def only_group(update: Update) -> bool:
    return update.effective_chat and update.effective_chat.id == GROUP_ID  # chat id vem do update. [web:419]

def conectar_google_sheets():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file("credenciais.json", scopes=scopes)
    return gspread.authorize(creds)

def get_ws():
    gc = conectar_google_sheets()
    sh = gc.open_by_key(SPREADSHEET_ID)
    try:
        ws = sh.worksheet(TAB_NAME)
    except Exception:
        ws = sh.add_worksheet(title=TAB_NAME, rows=200, cols=10)
        ws.append_row(["id", "item", "done", "added_by", "added_at", "done_by", "done_at"])
    return ws

def parse_id(x: str) -> int:
    try:
        return int(str(x).strip())
    except Exception:
        return 0

async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ajuda a obter o chat id diretamente pelo update. [web:423]
    await update.message.reply_text(f"chat_id = {update.effective_chat.id}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not only_group(update):
        return
    await update.message.reply_text(
        "🛒 Lista de compras (grupo)\n"
        "Adicionar: /add leite\n"
        "Ver lista: /list\n"
        "Marcar comprado: botão ✅"
    )

async def add_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not only_group(update):
        return

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
        # callback_data identifica qual item foi clicado. [web:481]
        keyboard.append([InlineKeyboardButton("✅ Comprado", callback_data=f"done:{item_id}")])
    return "\n".join(lines), InlineKeyboardMarkup(keyboard)

async def list_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not only_group(update):
        return
    ws = get_ws()
    text, markup = build_list_message_and_keyboard(ws)
    if markup:
        await update.message.reply_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # confirma o clique no botão. [web:477]

    if not only_group(update):
        await query.answer("Este bot só funciona no grupo configurado.", show_alert=True)
        return

    data = query.data or ""
    if not data.startswith("done:"):
        return

    item_id = data.split(":", 1)[1]
    user = update.effective_user

    ws = get_ws()
    rows = ws.get_all_values()

    target_row = None
    for idx, r in enumerate(rows[1:], start=2):  # linha 1 é header
        if len(r) >= 1 and str(r[0]) == str(item_id):
            target_row = idx
            break

    if not target_row:
        await query.edit_message_text("❌ Item não encontrado (talvez já foi marcado).")
        return

    ws.update_cell(target_row, 3, "TRUE")
    ws.update_cell(target_row, 6, str(user.id))
    ws.update_cell(target_row, 7, now_str())

    # Atualiza a própria mensagem com a lista atualizada (re-render). [web:477]
    text, markup = build_list_message_and_keyboard(ws)
    if markup:
        await query.edit_message_text(text, reply_markup=markup)
    else:
        await query.edit_message_text(text)

def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("Falta TELEGRAM_TOKEN")
    if not SPREADSHEET_ID:
        raise RuntimeError("Falta SPREADSHEET_ID")
    if not GROUP_ID:
        raise RuntimeError("Falta GROUP_ID")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("chatid", chatid))
    app.add_handler(CommandHandler("add", add_item))
    app.add_handler(CommandHandler("list", list_items))
    app.add_handler(CallbackQueryHandler(callback_handler))

    print("🤖 Bot lista família a correr")
    app.run_polling()

if __name__ == "__main__":
    main()
