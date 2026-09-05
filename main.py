import asyncio
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import os
import re
import threading
from zoneinfo import ZoneInfo
requests = __import__('requests')
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
TZ = ZoneInfo("Europe/Warsaw")


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

TOKEN = os.environ.get("BOT_TOKEN")
SCRAPER_API_KEY = "efd2da31c1fb502728ca866fdd35a3d5"
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
            ("Чоп (Тиса) — Захонь (≥ 7,5 т)", ["чоп", "тиса", "захонь"], False),
            (
                "Чоп (Тиса) — Захонь (Пустые ≥ 7,5 т)",
                ["чоп", "тиса", "захонь"],
                "порожн",
            ),
        ],
    },
    "SK": {
        "flag": "🇸🇰",
        "name": "Словакия",
        "items": [
            (
                "Ужгород — Вышне Немецке (≥ 7,5 т)",
                ["ужгород", "вишнє", "вышне"],
                False,
            ),
            (
                "Ужгород — Вышне Немецке (Пустые ≥ 7,5 т)",
                ["ужгород", "вишнє", "вышне"],
                "порожн",
            ),
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


def format_time_diff(target_dt):
  now = datetime.now(TZ)
  diff = target_dt - now
  if diff.total_seconds() <= 0:
    return "прямо сейчас"

  total_minutes = int(diff.total_seconds() // 60)
  days = total_minutes // (24 * 60)
  hours = (total_minutes % (24 * 60)) // 60
  minutes = total_minutes % 60

  parts = []
  if days > 0:
    parts.append(f"{days} дн.")
  if hours > 0 or days > 0:
    parts.append(f"{hours} ч.")
  parts.append(f"{minutes} мин.")
  return "через " + " ".join(parts)


def get_estimated_entry_datetime(wait_str):
  if (
      not wait_str
      or str(wait_str).lower() in ["none", "null", ""]
      or "без черги" in str(wait_str).lower()
  ):
    return None

  wait_str = str(wait_str).strip()
  now = datetime.now(TZ)

  if wait_str.isdigit():
    sec = int(wait_str)
    return now + timedelta(seconds=sec)

  days, hours, minutes = 0, 0, 0
  d_m = re.search(
      r"(\d+)\s*(?:дн|доб|день|дня|днів|дні|day|days)", wait_str, re.I
  )
  h_m = re.search(
      r"(\d+)\s*(?:год|годин|години|годину|час|часа|часов|hour|hours)",
      wait_str,
      re.I,
  )
  m_m = re.search(
      r"(\d+)\s*(?:хв|хвилин|хвилини|хвилину|мин|минут|min|minutes)",
      wait_str,
      re.I,
  )

  if d_m:
    days = int(d_m.group(1))
  if h_m:
    hours = int(h_m.group(1))
  if m_m:
    minutes = int(m_m.group(1))

  if days == 0 and hours == 0 and minutes == 0:
    return None

  return now + timedelta(days=days, hours=hours, minutes=minutes)


def parse_queue_items(data_obj):
  flattened = []
  items = (
      data_obj
      if isinstance(data_obj, list)
      else (
          data_obj.get("data", []) if isinstance(data_obj, dict) else [data_obj]
      )
  )
  if not isinstance(items, list):
    items = [items]

  for item in items:
    if not isinstance(item, dict):
      continue

    chk_name = str(
        item.get("name")
        or item.get("title")
        or item.get("checkpoint_name")
        or ""
    ).lower()
    queues = (
        item.get("queues")
        or item.get("items")
        or item.get("checkpoints")
        or item.get("workloads")
        or []
    )

    if isinstance(queues, list) and len(queues) > 0:
      for q in queues:
        if isinstance(q, dict):
          q_name = str(q.get("name") or q.get("title") or "").lower()
          full_name = f"{chk_name} {q_name}".strip()
          w_time = (
              q.get("waiting_time")
              or q.get("wait_time")
              or q.get("delay_time")
              or q.get("estimated_waiting_time")
              or q.get("wait")
          )
          flattened.append({
              "full_name": full_name,
              "waiting_time": str(w_time) if w_time is not None else "",
          })
    else:
      w_time = (
          item.get("waiting_time")
          or item.get("wait_time")
          or item.get("delay_time")
          or item.get("estimated_waiting_time")
      )
      flattened.append({
          "full_name": chk_name,
          "waiting_time": str(w_time) if w_time is not None else "",
      })

  return flattened


def fetch_live_echerha_queues():
  flattened_queues = []
  headers = {
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
      "Accept": "application/json, text/plain, */*",
      "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
  }

  for base_url in WORKLOAD_API_URLS:
    req_url = f"http://api.scraperapi.com?api_key={SCRAPER_API_KEY}&antibot=true&url={base_url}"
    try:
      res = requests.get(req_url, headers=headers, timeout=30)
      text = res.text.strip() if res.text else ""

      parsed_json = None
      if text.startswith(("[", "{")):
        try:
          parsed_json = json.loads(text)
        except Exception:
          pass

      if not parsed_json:
        match = re.search(r'([\[\{].*[\}\]])', text, re.DOTALL)
        if match:
          try:
            parsed_json = json.loads(match.group(1))
          except Exception:
            pass

      if parsed_json:
        extracted = parse_queue_items(parsed_json)
        if extracted:
          flattened_queues.extend(extracted)
      else:
        logging.warning(f"Не удалось извлечь JSON от {base_url}")
    except Exception as e:
      logging.error(f"Ошибка запроса {base_url}: {e}")

  return flattened_queues


def fetch_country_queue_report(country_code):
  country_info = CHECKPOINTS.get(country_code, {})
  country_name = country_info.get("name", "Граница")
  flag = country_info.get("flag", "📍")
  items = country_info.get("items", [])

  all_queues = fetch_live_echerha_queues()
  output_lines = [
      f"📊 **Фактическое время въезда последней машины: {flag} {country_name}**\n"
  ]

  for item_title, keywords, special_type in items:
    found_wait_time = None
    for entry in all_queues:
      full_name = entry["full_name"]
      wait_time = entry["waiting_time"]

      if any(k in full_name for k in keywords):
        if special_type is True and (
            "1-24" in full_name or "уктзед" in full_name
        ):
          found_wait_time = wait_time
          break
        elif special_type == "порожн" and (
            "порожн" in full_name
            or "пуст" in full_name
            or "empty" in full_name
        ):
          found_wait_time = wait_time
          break
        elif special_type is False and not (
            "1-24" in full_name
            or "порожн" in full_name
            or "пуст" in full_name
            or "уктзед" in full_name
        ):
          found_wait_time = wait_time
          break

    dt = get_estimated_entry_datetime(found_wait_time)
    if dt:
      dow = DAYS_RU[dt.weekday()]
      time_left = format_time_diff(dt)
      formatted_dt = f"{dt.strftime(f'%d.%m ({dow}) %H:%M')} ({time_left})"
    else:
      formatted_dt = "⚠️ Нет данных"

    output_lines.append(
        f"📍 **{item_title}**\n🚚 Последняя машина: {formatted_dt}\n"
    )

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
          InlineKeyboardButton("📋 Мои задачи", callback_data="show_tasks"),
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
              f"{info['flag']} {info['name']}",
              callback_data=f"status_show_{code}",
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

    report_text = await asyncio.to_thread(
        fetch_country_queue_report, cntry_code
    )

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
              f"{info['flag']} {info['name']}",
              callback_data=f"wiz_cntry_{code}",
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
    chk_item = CHECKPOINTS[cntry_code]["items"][chk_idx]

    user_wizard[chat_id]["checkpoint"] = chk_item[0]
    user_wizard[chat_id]["keywords"] = chk_item[1]
    user_wizard[chat_id]["special_type"] = chk_item[2]

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
        f"📅 **Шаг 3 из 4:** Выберите дату для **{chk_item[0]}**:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )

  elif data.startswith("wiz_date_"):
    date_val = data.split("_")[2]
    user_wizard[chat_id]["date"] = date_val

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
        f"⏰ **Шаг 4 из 4:** Выберите целевое время въезда на **{date_val}**:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )

  elif data.startswith("wiz_time_"):
    time_val = data.split("_")[2]
    wiz = user_wizard.get(chat_id, {})

    new_task = {
        "checkpoint": wiz.get("checkpoint", "КПП"),
        "keywords": wiz.get("keywords", []),
        "special_type": wiz.get("special_type", False),
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
        f"🎯 **Желаемый въезд:** `{new_task['target_date']} в {new_task['target_time']}`\n\n"
        f"🔔 Бот пришлёт уведомление, как только время въезда последней машины в очереди достигнет этой отметки!",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📋 Мои задачи", callback_data="show_tasks"),
            InlineKeyboardButton("🏠 Главное меню", callback_data="menu_main"),
        ]]),
        parse_mode="Markdown",
    )


def parse_target_datetime(date_str, time_str):
  now = datetime.now(TZ)
  for fmt in ["%d.%m.%Y %H:%M", "%d.%m %H:%M"]:
    try:
      if fmt == "%d.%m %H:%M":
        dt = datetime.strptime(f"{date_str} {time_str}", fmt)
        dt = dt.replace(year=now.year, tzinfo=TZ)
      else:
        dt = datetime.strptime(f"{date_str} {time_str}", fmt).replace(
            tzinfo=TZ
        )
      return dt
    except ValueError:
      continue
  return None


async def queue_checker_loop(app: Application):
  while True:
    try:
      tasks = load_tasks()
      if tasks:
        all_queues = await asyncio.to_thread(fetch_live_echerha_queues)

        for chat_id, user_tasks in list(tasks.items()):
          for task in list(user_tasks):
            target_dt = parse_target_datetime(
                task.get("target_date", ""), task.get("target_time", "")
            )
            if not target_dt:
              continue

            keywords = task.get("keywords", [])
            special_type = task.get("special_type", False)

            found_wait_time = None
            for entry in all_queues:
              full_name = entry["full_name"]
              if keywords and any(k in full_name for k in keywords):
                if special_type is True and (
                    "1-24" in full_name or "уктзед" in full_name
                ):
                  found_wait_time = entry["waiting_time"]
                  break
                elif special_type == "порожн" and (
                    "порожн" in full_name
                    or "пуст" in full_name
                    or "empty" in full_name
                ):
                  found_wait_time = entry["waiting_time"]
                  break
                elif special_type is False and not (
                    "1-24" in full_name
                    or "порожн" in full_name
                    or "пуст" in full_name
                    or "уктзед" in full_name
                ):
                  found_wait_time = entry["waiting_time"]
                  break

            if found_wait_time is not None and found_wait_time != "":
              last_truck_entry_dt = get_estimated_entry_datetime(
                  found_wait_time
              )

              if last_truck_entry_dt and last_truck_entry_dt >= target_dt:
                dow = DAYS_RU[last_truck_entry_dt.weekday()]
                time_left = format_time_diff(last_truck_entry_dt)
                actual_str = f"{last_truck_entry_dt.strftime(f'%d.%m ({dow}) %H:%M')} ({time_left})"

                await app.bot.send_message(
                    chat_id=int(chat_id),
                    text=(
                        f"🚨 **ПОРА СТАВИТЬ МАШИНУ В ОЧЕРЕДЬ!**\n\n"
                        f"📍 **КПП:** {task['checkpoint']}\n"
                        f"🎯 **Ваша цель:** `{task['target_date']} в {task['target_time']}`\n"
                        f"🚚 **Очередь (последняя машина) уже на:** `{actual_str}`\n\n"
                        f"👉 Регистрируйтесь прямо сейчас!"
                    ),
                    parse_mode="Markdown",
                )
                user_tasks.remove(task)
                save_tasks(tasks)
    except Exception as e:
      logging.error(f"Ошибка проверки алгоритма: {e}")

    await asyncio.sleep(30)


async def post_init(app: Application):
  asyncio.create_task(queue_checker_loop(app))


def main():
  app = Application.builder().token(TOKEN).post_init(post_init).build()
  app.add_handler(CommandHandler("start", start))
  app.add_handler(CallbackQueryHandler(handle_callback))

  print("🚀 Бот успешно запущен!")
  app.run_polling()


if __name__ == "__main__":
  main()
