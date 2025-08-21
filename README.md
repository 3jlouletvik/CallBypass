# MP Price Monitor (browser-fallback edition, Python 3.13 OK)

Это готовая программа на Python, которая следит за ценами и наличием товаров на **Wildberries** и **Ozon**.  
Если обычный запрос блокируется или не даёт цену, включается **запасной режим через headless-браузер (Playwright)**, который «видит» страницу как человек.

## Что умеет
- Хранит историю проверок в `prices.db` (SQLite)
- Присылает уведомления в Telegram (цена упала/выросла/достигла цели)
- Работает с `nmId` (WB) и URL (Ozon)
- Имеет фоллбеки: WB `cards` → WB `basket card.json` → HTML через браузер; Ozon requests → HTML через браузер

---

## Установка (пошагово)
Нужен Python **3.11–3.13**.

1) Распакуйте архив. Откройте терминал в папке проекта.

2) Создайте виртуальное окружение и активируйте его:
- macOS / Linux:
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```
- Windows (PowerShell):
  ```powershell
  py -3 -m venv .venv
  .\.venv\Scripts\Activate.ps1
  ```

3) Установите зависимости:
```bash
pip install -U pip
pip install -r requirements.txt
# для браузера (один раз скачать Chromium):
python -m playwright install chromium
```

4) Настройте Telegram:
```bash
cp .env.example .env
# откройте .env и вставьте свои TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID
```
> Напишите что-нибудь своему боту, чтобы он мог отправлять вам сообщения.

5) Добавьте цели мониторинга в `targets.csv`:
```csv
marketplace,sku,url,desired_price,rise_alert_pct,drop_alert_pct,notes
wb,12345678,,0,0,5,Пример WB nmId
ozon,,https://www.ozon.ru/product/slug-1215152100/,0,0,5,Пример Ozon URL
```

6) Запуск (разово):
```bash
.venv/bin/python monitor.py --run once
```
Циклический режим:
```bash
.venv/bin/python monitor.py --run loop --every 600
```

---

## Как это работает (чуть техподробностей)
- **WB**: пробует публичные `cards` v1/v2 с разными `dest`; если не нашёл — идёт в `basket-XX/.../card.json`; если и там пусто — открывает страницу карточки в браузере и вытаскивает цену из разметки.
- **Ozon**: сначала обычный запрос (с «прогревом» куки и чисткой query у URL); если нет цены/403 — открывает страницу в браузере и достаёт цену из JSON-LD/скриптов.

> Фоллбек через браузер включён по умолчанию (`BROWSER_FALLBACK=true` в `.env`). Можно выключить.

---

## Частые проблемы
- **SSL ошибки** → в `.env` можно временно поставить `SSL_VERIFY=false` (только для диагностики). В проекте используется `certifi`.
- **Ozon 403 / No data** → убедитесь, что вы установили браузер: `python -m playwright install chromium`. URL лучше без трекинговых хвостов (`?at=...`).
- **WB 404** → проверьте `nmId`. Откройте в браузере: `https://www.wildberries.ru/catalog/<nmId>/detail.aspx`.
- **Ничего не приходит в Telegram** → проверьте токен/чат, и напишите своему боту любое сообщение.

---

## Монетизация (быстро)
- Сделайте Telegram-бота с тарифами (лимит SKU, частота опросов), и продавайте мониторинг селлерам WB/Ozon.
- Добавьте отчёт «ТОП падений/ростов за сутки» и выгрузку в Google Sheets.

Удачи! Если что-то не стартует — пришлите команду, которую запускали, и последние строки лога.
