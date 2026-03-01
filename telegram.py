import os
import json
import shutil
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from dateutil import parser as dateparser
import asyncio

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import MessageEntityTextUrl, MessageEntityUrl

# ================== AUTH CONFIG ==================
API_ID = 'Your API_ID'
API_HASH = "Your API_HASH"
SESSION_NAME = os.path.join(os.path.expanduser("~"), "tg_session.session")
# ================================================

dialogs_cache = []

# ================== TELEGRAM ==================

async def create_client():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        phone = input("Введите номер телефона (+7999...): ")
        await client.send_code_request(phone)
        code = input("Введите код из Telegram: ")
        try:
            await client.sign_in(phone, code)
        except SessionPasswordNeededError:
            password = input("Введите пароль 2FA: ")
            await client.sign_in(password=password)

    return client


async def load_dialogs_async(log, dropdown):
    client = await create_client()
    dialogs = await client.get_dialogs()

    global dialogs_cache
    dialogs_cache = dialogs

    names = []
    for d in dialogs:
        if d.name:
            names.append(d.name)
        else:
            names.append(str(d.id))

    dropdown["values"] = names
    log(f"Загружено {len(names)} диалогов")
    await client.disconnect()


def check_disk_space(required_bytes):
    total, used, free = shutil.disk_usage(os.getcwd())
    return free >= required_bytes, free


def apply_entities_to_html(text, entities):
    if not text or not entities:
        return text

    for entity in sorted(entities, key=lambda e: e.offset, reverse=True):
        if isinstance(entity, MessageEntityTextUrl):
            link_text = text[entity.offset:entity.offset + entity.length]
            replacement = f'<a href="{entity.url}">{link_text}</a>'
            text = text[:entity.offset] + replacement + text[entity.offset + entity.length:]
        elif isinstance(entity, MessageEntityUrl):
            url = text[entity.offset:entity.offset + entity.length]
            replacement = f'<a href="{url}">{url}</a>'
            text = text[:entity.offset] + replacement + text[entity.offset + entity.length:]
    return text


async def estimate_size(client, entity, date_from, date_to, log):
    total_bytes = 0
    text_bytes = 0

    async for message in client.iter_messages(entity):
        if not message.date:
            continue
        msg_date = message.date.replace(tzinfo=None)
        if msg_date < date_from or msg_date > date_to:
            continue
        if message.text:
            text_bytes += len(message.text.encode("utf-8"))
        if message.file and message.file.size:
            total_bytes += message.file.size

    log(f"Оценка текста: {text_bytes / (1024**2):.2f} MB")
    log(f"Оценка медиа: {total_bytes / (1024**3):.2f} GB")
    return total_bytes + text_bytes


async def export_messages(chat, date_from, date_to, fmt, download_media, log):
    client = await create_client()

    # Определяем entity
    if isinstance(chat, str):
        entity = await client.get_entity(chat)
    else:
        entity = chat

    log("Оценка объёма скачивания...")
    estimated_size = await estimate_size(client, entity, date_from, date_to, log)

    ok, free = check_disk_space(estimated_size * 1.1)
    log(f"Свободно на диске: {free / (1024**3):.2f} GB")
    if not ok:
        log("Недостаточно свободного места.")
        await client.disconnect()
        return

    if download_media:
        os.makedirs("media", exist_ok=True)

    messages = []
    log("Начинаем экспорт...")

    async for message in client.iter_messages(entity, reverse=True):
        if not message.date:
            continue
        msg_date = message.date.replace(tzinfo=None)
        if msg_date < date_from or msg_date > date_to:
            continue

        sender = await message.get_sender()
        sender_name = getattr(sender, "username", None) or getattr(sender, "first_name", "Unknown")
        text = message.text or ""
        html_text = apply_entities_to_html(text, message.entities or [])
        media_path = None
        if download_media and message.media:
            media_path = await message.download_media(file="media")

        messages.append({
            "date": msg_date.isoformat(),
            "sender": sender_name,
            "text": text,
            "html": html_text,
            "media": media_path
        })

    output_file = f"export.{fmt}"
    if fmt == "json":
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(messages, f, ensure_ascii=False, indent=4)
    else:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("<html><body>")
            for m in messages:
                f.write(f"<p><b>{m['date']} | {m['sender']}</b><br>{m['html']}")
                if m["media"]:
                    f.write(f"<br><i>Media:</i> {m['media']}")
                f.write("</p><hr>")
            f.write("</body></html>")

    log(f"Готово. Экспортировано {len(messages)} сообщений.")
    await client.disconnect()


# ================== GUI ==================

def start_export():
    selected_dialog_name = dialog_var.get()
    manual_input = chat_entry.get().strip()
    chat = None

    if selected_dialog_name:
        for d in dialogs_cache:
            if d.name == selected_dialog_name:
                chat = d.entity
                break
    if not chat and manual_input:
        chat = manual_input.replace("https://t.me/", "").replace("@", "")
    if not chat:
        messagebox.showerror("Ошибка", "Выберите диалог или введите чат вручную")
        return

    try:
        date_from = dateparser.parse(date_from_entry.get())
        date_to = dateparser.parse(date_to_entry.get())
    except:
        messagebox.showerror("Ошибка", "Неверный формат даты")
        return

    fmt = format_var.get()
    download_media = media_var.get()

    def log(message):
        log_box.insert(tk.END, message + "\n")
        log_box.see(tk.END)

    def run_async():
        asyncio.run(export_messages(chat, date_from, date_to, fmt, download_media, log))

    threading.Thread(target=run_async).start()


def refresh_dialogs():
    def log(message):
        log_box.insert(tk.END, message + "\n")
        log_box.see(tk.END)

    def run():
        asyncio.run(load_dialogs_async(log, dialog_dropdown))

    threading.Thread(target=run).start()


# ================== WINDOW ==================

root = tk.Tk()
root.title("Telegram Export Tool")

tk.Label(root, text="Выбрать диалог:").pack()
dialog_var = tk.StringVar()
dialog_dropdown = ttk.Combobox(root, textvariable=dialog_var, width=60)
dialog_dropdown.pack()
tk.Button(root, text="Обновить список диалогов", command=refresh_dialogs).pack(pady=3)

tk.Label(root, text="Или ввести вручную (@username / ссылка / id):").pack()
chat_entry = tk.Entry(root, width=60)
chat_entry.pack()

tk.Label(root, text="Дата от (YYYY-MM-DD):").pack()
date_from_entry = tk.Entry(root)
date_from_entry.pack()
tk.Label(root, text="Дата до (YYYY-MM-DD):").pack()
date_to_entry = tk.Entry(root)
date_to_entry.pack()

format_var = tk.StringVar(value="html")
ttk.Label(root, text="Формат:").pack()
ttk.Combobox(root, textvariable=format_var, values=["html", "json"]).pack()

media_var = tk.BooleanVar()
tk.Checkbutton(root, text="Скачивать медиа", variable=media_var).pack()

tk.Button(root, text="Запустить экспорт", command=start_export).pack(pady=5)

log_box = tk.Text(root, height=15, width=90)
log_box.pack()

root.mainloop()
