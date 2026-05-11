# Fitness Platform

Персональная веб-платформа для трекинга тренировок, восстановления и питания. Flask + SQLite + Chart.js + опциональные интеграции с **Polar AccessLink** и **Anthropic Claude**.

## Что это

Одностраничное (на самом деле — четырёхстраничное) приложение для одного пользователя.

- **Dashboard** — Nightly Recharge, HRV, нагрузка, пульс покоя, график нагрузки vs восстановления, фазы сна, последние тренировки, рекомендация на сегодня, мини-календарь.
- **Calendar** — полный месячный календарь с цветными метками тренировок. Клик по дню — детали + заметка.
- **Nutrition** — БЖУ + калории за сегодня, журнал приёмов пищи, график веса 14 дней, мои продукты.
- **AI Trainer** — чат с Claude, который видит твои данные. Кнопка «Скачать FIT-файл» создаёт план недели в формате `.fit`.

Темная тема, иконочный сайдбар 56px, без CSS-фреймворков, без JS-фреймворков.

## Установка

Требуется Python 3.11+.

```bash
git clone https://github.com/wasesroge-jpg/fitness-platform.git
cd fitness-platform
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                  # затем заполни ключи (опционально)
python -m app.app
```

Открой [http://localhost:5000](http://localhost:5000).

При первом запуске БД `app/data.db` создаётся автоматически. Если она пуста — загружаются демо-данные за последние 30 дней (восстановление, HRV, сон, ~20 тренировок, питание, вес, продукты). Так что приложение **работает сразу без всяких API-ключей**.

## Запуск с mock-данными

Просто запусти приложение. Если в `.env` нет `POLAR_ACCESS_TOKEN` / `ANTHROPIC_API_KEY` — всё равно всё работает:

- Polar заменяется на 30 дней демо-данных, эндпоинт `/sync` сообщит, что креды не настроены.
- AI-чат работает в локальном режиме: выдаёт data-driven ответы на основе твоих 14 дней (без обращения к Claude).

## Polar AccessLink

1. Зарегистрируй приложение: https://admin.polaraccesslink.com/
2. Получи `client_id`, `client_secret`, авторизуй пользователя по OAuth, забери `access_token` и `user_id`.
3. Положи всё в `.env`:
   ```
   POLAR_CLIENT_ID=...
   POLAR_CLIENT_SECRET=...
   POLAR_ACCESS_TOKEN=...
   POLAR_USER_ID=...
   ```
4. Открой `/sync` — это вызовет `PolarClient.sync_last_30_days()` и положит данные в SQLite.

## Anthropic (Claude)

1. Получи ключ в [console.anthropic.com](https://console.anthropic.com/).
2. Добавь в `.env`:
   ```
   ANTHROPIC_API_KEY=...
   ```
3. Перезапусти `python -m app.app`. На вкладке AI Trainer ответы пойдут от Claude (`claude-sonnet-4-20250514`).

## Структура

```
app/
  app.py            # Flask, все маршруты
  database.py       # SQLite + запросы
  polar.py          # Клиент Polar AccessLink
  ai_trainer.py     # Контекст для Claude + fallback
  fit_export.py     # Генерация .fit-файла плана недели
  mock_data.py      # Демо-данные за 30 дней
  static/style.css  # Темная тема
  static/app.js     # Графики (Chart.js) + интерактив
  templates/
    base.html
    dashboard.html
    calendar.html
    nutrition.html
    ai_trainer.html
```

## Деплой на Railway

1. Создай новый Railway-проект из этого репозитория.
2. Установи переменные окружения из `.env.example`.
3. Railway автоматически подхватит `requirements.txt`. Команда запуска:
   ```
   gunicorn app.app:app -b 0.0.0.0:$PORT
   ```
   (добавь `gunicorn` в `requirements.txt`, если нужен прод-сервер).
4. Сохраняй базу данных: используй Railway Volume и пробрось переменную `FITNESS_DB_PATH=/data/data.db`.

## Заметки по реализации

- Все даты — ISO `YYYY-MM-DD`.
- Тренировочная нагрузка и БЖУ округляются до 1 знака.
- Сайдбар автоматически переезжает вниз на экранах ≤ 600px.
- Аутентификации нет — это персональный инструмент.
- Чтобы перезагрузить демо-данные, удали `app/data.db` и запусти заново.
