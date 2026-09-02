#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sonar — бесплатный автопостер крипто-новостей в Telegram-канал.

Что делает:
  1. Читает несколько RSS-лент крипто-изданий (см. FEEDS ниже).
  2. Отбирает записи новее, чем POSTED_LOG (чтобы не дублировать посты
     между запусками).
  3. Публикует каждую новую запись в Telegram-канал через Bot API.

Как запускать:
  - Локально:  TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python3 post_news.py
  - По расписанию бесплатно: см. .github/workflows/post_news.yml —
    GitHub Actions запускает этот файл каждый час, ничего платить не нужно
    (в публичном репозитории Actions бесплатны без лимита минут).

Настройка:
  - TELEGRAM_BOT_TOKEN — токен бота от @BotFather.
  - TELEGRAM_CHAT_ID   — @username канала (для публичного канала) либо
                          числовой chat_id (для приватного, узнать через
                          @userinfobot, переслав ему сообщение из канала).
  - Оба значения хранить в GitHub Actions как Secrets, не в коде.
"""

import os
import sys
import json
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

# --- Источники новостей (RSS), только на русском. Добавляй/убирай по вкусу.
FEEDS = [
    {"name": "Cointelegraph", "url": "https://ru.cointelegraph.com/rss"},
    {"name": "ForkLog", "url": "https://forklog.com/feed"},
]

# Сколько новых новостей публиковать за один запуск (защита от спама,
# если лента долго не запускалась и накопилось много записей)
MAX_POSTS_PER_RUN = 3

# Файл, в котором храним ссылки на уже опубликованные новости
STATE_FILE = Path(__file__).parent / "posted_log.json"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def load_posted() -> set:
    if STATE_FILE.exists():
        try:
            return set(json.loads(STATE_FILE.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_posted(posted: set) -> None:
    # храним только последние 500 ссылок, чтобы файл не рос бесконечно
    trimmed = list(posted)[-500:]
    STATE_FILE.write_text(json.dumps(trimmed, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_feed(url: str, timeout: int = 15):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (SonarBot/1.0)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    root = ET.fromstring(data)
    items = []
    # RSS 2.0: rss/channel/item ; Atom: feed/entry — обрабатываем оба
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if title and link:
            items.append({"title": title, "link": link})
    if not items:
        for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
            title = (entry.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
            link_el = entry.find("{http://www.w3.org/2005/Atom}link")
            link = link_el.get("href") if link_el is not None else ""
            if title and link:
                items.append({"title": title, "link": link})
    return items


def send_telegram_message(text: str) -> bool:
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        # без превью-карточки — просто короткая ссылка "(читать)" в тексте
        "disable_web_page_preview": True,
    }
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(api_url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return bool(result.get("ok"))
    except Exception as exc:
        print(f"[error] send failed: {exc}", file=sys.stderr)
        return False


def format_message(item: dict, source_name: str) -> str:
    return (
        f"📰 <b>{item['title']}</b>\n"
        f'{source_name} · <a href="{item["link"]}">(читать)</a>'
    )


def main() -> int:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[error] Задай TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID (env vars / GitHub Secrets).",
              file=sys.stderr)
        return 1

    posted = load_posted()
    new_posts = 0

    for feed in FEEDS:
        try:
            items = fetch_feed(feed["url"])
        except Exception as exc:
            print(f"[warn] не удалось прочитать {feed['name']}: {exc}", file=sys.stderr)
            continue

        for item in items:
            if new_posts >= MAX_POSTS_PER_RUN:
                break
            if item["link"] in posted:
                continue

            message = format_message(item, feed["name"])
            if send_telegram_message(message):
                print(f"[ok] posted: {item['title'][:70]}")
                posted.add(item["link"])
                new_posts += 1
                time.sleep(2)  # с запасом ниже лимита Bot API (~1 msg/sec в чат)
            else:
                print(f"[fail] не отправлено: {item['title'][:70]}", file=sys.stderr)

        if new_posts >= MAX_POSTS_PER_RUN:
            break

    save_posted(posted)
    print(f"[done] опубликовано новых постов: {new_posts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
