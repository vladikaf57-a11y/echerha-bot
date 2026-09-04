import urllib3

# Отключаем предупреждения о необрабатываемых SSL-сертификатах
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def fetch_live_echerha_queues():
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
          " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
      ),
      "Accept": "application/json, text/plain, */*",
      "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
      "Referer": "https://echerha.gov.ua/workload",
      "Origin": "https://echerha.gov.ua",
  }

  flattened_queues = []
  session = requests.Session()

  for url in WORKLOAD_API_URLS:
    try:
      # verify=False обходит ошибки SSL-сертификата .gov.ua на серверах Render
      res = session.get(url, headers=headers, timeout=12, verify=False)
      if res.status_code == 200:
        data = res.json()
        items = data if isinstance(data, list) else data.get("data", [data])
        for item in items:
          if isinstance(item, dict):
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
                or []
            )

            if isinstance(queues, list) and len(queues) > 0:
              for q in queues:
                if isinstance(q, dict):
                  q_name = str(q.get("name") or q.get("title") or "").lower()
                  full_name = f"{chk_name} {q_name}"
                  w_time = (
                      q.get("waiting_time")
                      or q.get("wait_time")
                      or q.get("delay_time")
                      or q.get("estimated_waiting_time")
                      or q.get("wait")
                  )
                  flattened_queues.append({
                      "full_name": full_name,
                      "waiting_time": (
                          str(w_time) if w_time is not None else ""
                      ),
                  })
            else:
              w_time = (
                  item.get("waiting_time")
                  or item.get("wait_time")
                  or item.get("delay_time")
                  or item.get("estimated_waiting_time")
              )
              flattened_queues.append({
                  "full_name": chk_name,
                  "waiting_time": str(w_time) if w_time is not None else "",
              })
      else:
        logging.warning(
            f"API {url} вернул статус {res.status_code}: {res.text[:100]}"
        )
    except Exception as e:
      logging.error(f"Ошибка обращения к API {url}: {e}")

  return flattened_queues
