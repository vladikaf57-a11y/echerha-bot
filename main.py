import asyncio
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import os
import re
import threading
from zoneinfo import ZoneInfo
import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# Установка часового пояса (Польша / Украина)
TZ = ZoneInfo("Europe/Warsaw")


# Микро-сервер для пинга на Render.com
class HealthCheckHandler(BaseHTTPRequestHandler):

  def do_GET(self):
    self.send_response(200)
    self.end_headers()
    self.wfile.write(b"Bot is alive")


def run_health_server():
  port = int(os.environ.get("PORT", 8080))
  server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
  server.serve_forever()


threading.Thread(target=run_health_server, daemon=True).start()

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)

TOKEN = "8982444944:AAFznR-8oCVMkMsMrlFu1FTm7FiEt4KO8Do"
TASKS_FILE = "tasks.json"

WORKLOAD_API_URLS = [
    "https://echerha.gov.ua/api/v4/workload/1",
    "https://echerha.gov.ua/api/v4/workload/2",
    "https://echerha.gov.ua/api/v4/workload/3",
]
DAYS_RU = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

CHECKPOINTS = {
    "PL": {
        "flag": "🇵🇱",
        "name": "Польша",
        "items": [
            ("Краковец — Корчевая (≥ 7,5 т)", ["краківець", "краковец"], False),
            (
                "Краковец — Корчёва. Товары 1-24 (≥ 7,5 т)",
                ["краківець", "краковец"],
                True,
            ),
            ("Рава-Русская — Хребенне (≥ 7,5 т)", ["рава"], False),
            (
                "Рава-Русская — Хребенне. Товары 1-24 (≥ 7,5 т)",
                ["рава"],
                True,
            ),
            ("Ягодин — Дорогуск (≥ 7,5 т)", ["ягодин"], False),
            ("Ягодин — Дорогуск. Товары 1-24 (≥ 7,5 т)", ["ягодин"], True),
            ("Ягодин — Дорогуск (Пустые ≥ 7,5 т)", ["ягодин"], "порожн"),
            ("Шегини — Медика (≥ 7,5 т)", ["шегині", "шегини"], False),
            ("Шегини — Медика. Товары 1-24 (≥ 7,5 т)", ["шегині", "шегини"], True),
            ("Устилуг — Зосин (Пустые ≥ 7,5 т)", ["устилуг"], "порожн"),
            (
                "Нижанковичи — Мальховице (Пустые ≥ 7,5 т)",
                ["нижанковичі", "нижанковичи"],
                "порожн",
            ),
        ],
    },
    "RO": {
        "flag": "🇷🇴",
        "name": "Румыния",
        "items": [
            ("Порубное — Сирет (≥ 7,5 т)", ["порубне", "порубное"], False),
            (
                "Порубное — Сирет. Товары 1-24 (≥ 7,5 т)",
                ["порубне", "порубное"],
                True,
            ),
            (
                "Порубное — Сирет (Пустые ≥ 7,5 т)",
                ["порубне", "порубное"],
                "порожн",
            ),
            ("Дяково — Халмеу (≥ 7,5 т)", ["дякове", "дяково"], False),
            ("Дяково — Халмеу. Товары 1-24 (≥ 7,5 т)", ["дякове", "дяково"], True),
            ("Орловка — Исакча (≥ 7,5 т)", ["орлівка", "орловка"], False),
        ],
    },
    "MD": {
        "flag": "🇲🇩",
        "name": "Молдова",
        "items": [
            ("Могилев-Подольский — Отач (≥ 7,5 т)", ["могилів", "могилев"], False),
            ("Маяки-Удобное-Паланка (≥ 7,5 т)", ["маяки"], False),
            ("Рени — Джурджулешты (≥ 7,5 т)", ["рені", "рени"], False),
            ("Староказачье — Тудора (≥ 7,5 т)", ["старокозаче", "староказачье"], False),
            (
                "Виноградовка — Вулканешты (≥ 7,5 т)",
                ["виноградівка", "виноградовка"],
                False,
            ),
        ],
    },
    "HU": {
        "flag": "🇭🇺",
        "name": "Венгрия",
        "items": [
            ("Чоп (Тиса) — Захонь (≥ 7,5 т)", ["чоп"], False),
            ("Чоп (Тиса) — Захонь (Пустые ≥ 7,5 т)", ["чоп"], "порожн"),
        ],
    },
    "SK": {
        "flag": "🇸🇰",
        "name": "Словакия",
        "items": [
            ("Ужгород — Вышне Немецке (≥ 7,5 т)", ["ужгород"], False),
            ("Ужгород — Вышне Немецке (Пустые ≥ 7,5 т)", ["ужгород"], "порожн"),
        ],
    },
}


def load_tasks():
  if os.path.exists(TASKS_FILE):
    try:
      with open(TASKS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)
    except Exception:
      return {}
  return {}


def save_tasks(tasks):
  with open(TASKS_FILE, "w", encoding="utf-8") as f:
    json.dump(tasks, f, ensure_ascii=False, indent=2)


user_wizard = {}


def parse_wait_time_to_datetime(wait_str):
  if not wait_str or "0 хв" in wait_str or "без черги" in wait_str.lower():
    return "🟢 Без очереди"

  now = datetime.now(TZ)
  days, hours, minutes = 0, 0, 0

  d_m = re.search(r"(\d+)\s*(?:дн|доб|день|дня|днів|дні)", wait_str, re.I)
  h_m = re.search(
      r"(\d+)\s*(?:год|годин|години|годину|час|часа|часов)", wait_str, re.I
  )
  m_m = re.search(
      r"(\d+)\s*(?:хв|хвилин|хвилини|хвилину|мин|минут)", wait_str, re.I
  )

  if d_m:
    days = int(d_m.group(1))
  if h_m:
    hours = int(h_m.group(1))
  if m_m:
    minutes = int(m_m.group(1))

  if days == 0 and hours == 0 and minutes == 0:
    return "🟢 Без очереди"

  dt = now + timedelta(days=days, hours=hours, minutes=minutes)
  dow = DAYS_RU[dt.weekday()]
  return dt.strftime(f"%d.%m ({dow}) %H:%M")


def fetch_live_echerha_data():
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
      ),
      "Accept": "application/json, text/plain, */*",
  }
  raw_data = []
  for url in WORKLOAD_API_URLS:
    try:
      res = requests.get(url, headers=headers, timeout=8)
      if res.status_code == 200:
        data = res.json()
        if isinstance(data, list):
          raw_data.extend(data)
        elif isinstance(data, dict) and "data" in data:
          raw_data.extend(data["data"])
    except Exception as e:
      logging.error(f"Ошибка получения API {url}: {e}")
  return raw_data


def fetch_country_queue_report(country_code):
  country_info = CHECKPOINTS.get(country_code, {})
  country_name = country_info.get("name", "Граница")
  flag = country_info.get("flag", "📍")
  items = country_info.get("items", [])

  api_data = fetch_live_echerha_data()
  output_lines = [
      f"📊 **Ориентировочное время въезда (последняя машина): {flag}"
      f" {country_name}**\n"
  ]

  for item_title, keywords, special_type in items:
    found_wait_time = None
    for entry in api_data:
      name = str(
          entry.get("name", "")
          or entry.get("title", "")
          or entry.get("checkpoint_name", "")
      ).lower()
      wait_time = str(
          entry.get("waiting_time", "")
          or entry.get("wait_time", "")
          or entry.get("delay_time", "")
      )

      if any(k in name for k in keywords):
        if special_type is True and ("1-24" in name or "уктзед" in name):
          found_wait_time = wait_time
          break
        elif special_type == "порожн" and (
            "порожн" in name or "пуст" in name or "empty" in name
        ):
          found_wait_time = wait_time
          break
        elif special_type is False and not (
            "1-24" in name or "порожн" in name or "пуст" in name
        ):
          found_wait_time = wait_time
          break

    if found_wait_time is not None:
      formatted_dt = parse_wait_time_to_datetime(found_wait_time)
    else:
      formatted_dt = "⚠️ Нет данных"

    output_lines.append(f"📍 **{item_title}**\n🚚 {formatted_dt}\n")

  now = datetime.now(TZ)
  dow = DAYS_RU[now.weekday()]
  output_lines.append(f"🕒 _Обновлено: {now.strftime(f'%d.%m ({dow}) %H:%M')}_")
  return "\n".join(output_lines)


def main_keyboard():
  return InlineKeyboardMarkup([
      [
          InlineKeyboardButton(
              "➕ Добавить отслеживание", callback_data="wizard_start"
          )
      ],
      [
          InlineKeyboardButton(
              "📋 Мои задачи", callback_data="show_tasks"
          ),
          InlineKeyboardButton(
              "📊 Очередь сейчас", callback_data="status_select_country"
          ),
      ],
  ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
  await update.message.reply_text(
      "🚚 **Мониторинг очереди єЧерга (Грузовые ≥ 7,5 т)**\n\n"
      "Выберите раздел в меню ниже:",
      reply_markup=main_keyboard(),
      parse_mode="Markdown",
  )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
  query = update.callback_query
  await query.answer()
  data = query.data
  chat_id = str(query.message.chat_id)

  if data == "menu_main":
    await query.message.edit_text(
        "🏠 **Главное меню**",
        reply_markup=main_keyboard(),
        parse_mode="Markdown",
    )

  elif data == "status_select_country":
    buttons = []
    for code, info in CHECKPOINTS.items():
      buttons.append([
          InlineKeyboardButton(
              f"{info['flag']} {info['name']}", callback_data=f"status_show_{code}"
          )
      ])
    buttons.append(
        [InlineKeyboardButton("🏠 Главное меню", callback_data="menu_main")]
    )
    await query.message.edit_text(
        "🌍 **Выберите страну:**",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )

  elif data.startswith("status_show_"):
    cntry_code = data.split("_")[2]
    await query.message.edit_text(
        "⏳ *Загружаю текущие данные єЧерга...*", parse_mode="Markdown"
    )

    report_text = fetch_country_queue_report(cntry_code)

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔄 Обновить", callback_data=f"status_show_{cntry_code}"
            )
        ],
        [
            InlineKeyboardButton(
                "🌍 Другая страна", callback_data="status_select_country"
            )
        ],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="menu_main")],
    ])
    await query.message.edit_text(
        report_text, reply_markup=kb, parse_mode="Markdown"
    )

  elif data == "show_tasks":
    tasks = load_tasks()
    user_tasks = tasks.get(chat_id, [])

    if not user_tasks:
      kb = InlineKeyboardMarkup(
          [[InlineKeyboardButton("🔙 Главное меню", callback_data="menu_main")]]
      )
      await query.message.edit_text(
          "ℹ️ **У вас нет активных задач.**",
          reply_markup=kb,
          parse_mode="Markdown",
      )
      return

    text = "📋 **Ваши активные задачи:**\n\n"
    buttons = []
    for idx, task in enumerate(user_tasks):
      short_chk = task["checkpoint"].split("—")[0].strip()
      text += (
          f"📍 **{task['checkpoint']}**\n"
          f"⏰ Цель: `{task['target_date']} в {task['target_time']}`\n\n"
      )
      buttons.append([
          InlineKeyboardButton(
              f"❌ Удалить: {short_chk} ({task['target_time']})",
              callback_data=f"del_task_{idx}",
          )
      ])

    buttons.append(
        [InlineKeyboardButton("🔙 Главное меню", callback_data="menu_main")]
    )
    await query.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown"
    )

  elif data.startswith("del_task_"):
    idx_to_del = int(data.split("_")[2])
    tasks = load_tasks()
    if chat_id in tasks and 0 <= idx_to_del < len(tasks[chat_id]):
      removed = tasks[chat_id].pop(idx_to_del)
      save_tasks(tasks)
      await query.message.edit_text(
          f"✅ Задача **{removed['checkpoint']}** удалена!",
          reply_markup=InlineKeyboardMarkup([[
              InlineKeyboardButton("📋 К задачам", callback_data="show_tasks")
          ]]),
          parse_mode="Markdown",
      )

  elif data == "wizard_start":
    user_wizard[chat_id] = {}
    buttons = []
    for code, info in CHECKPOINTS.items():
      buttons.append([
          InlineKeyboardButton(
              f"{info['flag']} {info['name']}", callback_data=f"wiz_cntry_{code}"
          )
      ])
    buttons.append(
        [InlineKeyboardButton("❌ Отмена", callback_data="menu_main")]
    )
    await query.message.edit_text(
        "🌍 **Шаг 1 из 4:** Выберите страну:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )

  elif data.startswith("wiz_cntry_"):
    cntry_code = data.split("_")[2]
    user_wizard[chat_id]["country"] = cntry_code
    cntry = CHECKPOINTS[cntry_code]

    buttons = []
    for idx, item in enumerate(cntry["items"]):
      item_title = item[0]
      buttons.append([
          InlineKeyboardButton(
              f"📍 {item_title}", callback_data=f"wiz_chk_{cntry_code}_{idx}"
          )
      ])
    buttons.append(
        [InlineKeyboardButton("⬅️ Назад", callback_data="wizard_start")]
    )

    await query.message.edit_text(
        f"📍 **Шаг 2 из 4:** Выберите пункт пропуска ({cntry['name']}):",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )

  elif data.startswith("wiz_chk_"):
    parts = data.split("_")
    cntry_code = parts[2]
    chk_idx = int(parts[3])
    chk_name = CHECKPOINTS[cntry_code]["items"][chk_idx][0]

    user_wizard[chat_id]["checkpoint"] = chk_name

    today = datetime.now(TZ)
    days_map = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    buttons = []

    for i in range(7):
      d = today + timedelta(days=i)
      date_str = d.strftime("%d.%m.%Y")
      day_name = days_map[d.weekday()]
      label = (
          f"📅 Сегодня ({d.strftime('%d.%m')})"
          if i == 0
          else f"📅 {d.strftime('%d.%m')} ({day_name})"
      )
      buttons.append(
          [InlineKeyboardButton(label, callback_data=f"wiz_date_{date_str}")]
      )

    buttons.append([
        InlineKeyboardButton(
            "⬅️ Назад", callback_data=f"wiz_cntry_{cntry_code}"
        )
    ])

    await query.message.edit_text(
        f"📅 **Шаг 3 из 4:** Выберите дату для **{chk_name}**:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )

  elif data.startswith("wiz_date_"):
    date_val = data.split("_")[2]
    user_wizard[chat_id]["date"] = date_val

    # ВЫБОР ВРЕМЕНИ С ШАГОМ 30 МИНУТ (СЕТКА ПО 4 КНОПКИ В РЯД)
    time_options = []
    for h in range(24):
      for m in (0, 30):
        time_options.append(f"{h:02d}:{m:02d}")

    buttons = []
    row = []
    for t in time_options:
      row.append(InlineKeyboardButton(t, callback_data=f"wiz_time_{t}"))
      if len(row) == 4:
        buttons.append(row)
        row = []
    if row:
      buttons.append(row)

    buttons.append(
        [InlineKeyboardButton("❌ Отмена", callback_data="menu_main")]
    )

    await query.message.edit_text(
        f"⏰ **Шаг 4 из 4:** Выберите точное время на **{date_val}**:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )

  elif data.startswith("wiz_time_"):
    time_val = data.split("_")[2]
    wiz = user_wizard.get(chat_id, {})

    new_task = {
        "checkpoint": wiz.get("checkpoint", "КПП"),
        "target_date": wiz.get("date", ""),
        "target_time": time_val,
        "created_at": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),
    }

    tasks = load_tasks()
    if chat_id not in tasks:
      tasks[chat_id] = []
    tasks[chat_id].append(new_task)
    save_tasks(tasks)

    if chat_id in user_wizard:
      del user_wizard[chat_id]

    await query.message.edit_text(
        f"✅ **Отслеживание установлено!**\n\n"
        f"📍 **Пункт:** {new_task['checkpoint']}\n"
        f"📅 **Целевое время:** `{new_task['target_date']} в {new_task['target_time']}`\n\n"
        f"🔔 Бот автоматически уведомит вас в этом чате!",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📋 Мои задачи", callback_data="show_tasks"),
            InlineKeyboardButton("🏠 Главное меню", callback_data="menu_main"),
        ]]),
        parse_mode="Markdown",
    )


async def queue_checker_loop(app: Application):
  while True:
    try:
      tasks = load_tasks()
      if tasks:
        now_dt = datetime.now(TZ)
        for chat_id, user_tasks in list(tasks.items()):
          for task in list(user_tasks):
            try:
              target_dt = datetime.strptime(
                  f"{task['target_date']} {task['target_time']}",
                  "%d.%m.%Y %H:%M",
              ).replace(tzinfo=TZ)

              if now_dt >= target_dt:
                await app.bot.send_message(
                    chat_id=int(chat_id),
                    text=(
                        f"🚨 **ПОРА СТАВИТЬ МАШИНУ В ОЧЕРЕДЬ!**\n\n"
                        f"📍 КПП: **{task['checkpoint']}**\n"
                        f"⏰ Ваше время: `{task['target_date']}"
                        f" {task['target_time']}`\n\n"
                        f"👉 Зайдите на сайт єЧерга и зарегистрируйтесь!"
                    ),
                    parse_mode="Markdown",
                )
                user_tasks.remove(task)
                save_tasks(tasks)
            except Exception as task_err:
              logging.error(f"Ошибка проверки задачи: {task_err}")
    except Exception as e:
      logging.error(f"Ошибка фоновой проверки: {e}")

    await asyncio.sleep(30)


async def post_init(app: Application):
  asyncio.create_task(queue_checker_loop(app))


def main():
  app = Application.builder().token(TOKEN).post_init(post_init).build()
  app.add_handler(CommandHandler("start", start))
  app.add_handler(CallbackQueryHandler(handle_callback))

  print("🚀 Бот запущен с точным расчетом и фоновой проверкой каждые 30 сек.")
  app.run_polling()


if __name__ == "__main__":
  main()
