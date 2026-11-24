# hh-pars

Telegram-бот (`@ggparswolstbot`), который по пресетам пользователей парсит вакансии
с hh.ru (HTML-страница поиска — JSON API отдаёт 403 датацентровым IP) и присылает новые в чат.

Стек: Python 3.12, aiogram 3, httpx, SQLAlchemy (async) + PostgreSQL, APScheduler, Docker.

## Структура

```
src/
  config.py        # настройки из .env (pydantic-settings)
  hh_client.py      # парсер страницы поиска hh.ru
  parser.py         # логика поиска новых вакансий и сохранения в БД
  bot/handlers.py   # хендлеры aiogram
  storage/          # SQLAlchemy модели + подключение к БД
  main.py           # точка входа: бот + планировщик
tests/
.github/workflows/  # CI и CD
```

## Быстрый старт

```bash
cp .env.example .env   # заполнить токены
docker compose up --build
```

## Переменные окружения

См. [.env.example](.env.example):

- `HH_CLIENT_ID` / `HH_CLIENT_SECRET` / `HH_ACCESS_TOKEN` — нужны только если требуется
  доступ к приватным данным hh.ru API (обычный поиск вакансий работает без токена, но требует `HH_USER_AGENT`).
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — бот и чат для уведомлений.
- `DATABASE_URL` — строка подключения к PostgreSQL.
- `HH_PROXY_URL` — прокси для запросов к hh.ru (на главном узле — SOCKS RU-ноды).
- `TELEGRAM_PROXY_URL` — прокси к Telegram API, только где он заблокирован.
- `PARSE_INTERVAL_MINUTES`, `HH_SEARCH_TEXT`, `HH_SEARCH_AREA` — параметры парсинга.

## CI/CD

### CI (`.github/workflows/ci.yml`)

На каждый push/PR в `main`: линт (ruff), тесты (pytest), пробная сборка Docker-образа.
Выполняется на обычных github-hosted раннерах, публикации никуда не делает.

### CD (`.github/workflows/cd.yml`)

На каждый push в `main` (и тег `v*`):

1. `build-and-push` собирает образ и пушит в GHCR: `ghcr.io/ggwolst/hh-pars:latest` и `:<sha коммита>`.
2. `deploy` заходит по SSH на главный узел и запускает там `deploy.sh` с образом этого коммита.

Деплой включается переменной репозитория `DEPLOY_ENABLED=true` и секретами
`SSH_HOST`, `SSH_PORT`, `SSH_USER`, `SSH_KEY`, `SSH_FINGERPRINT`. Без них job пропускается,
образ всё равно собирается.

## Деплой (главный узел)

Бот живёт на главном узле инфраструктуры, а не в локальной сети:

- приложение — `/root/hh-pars`: `docker-compose.prod.yml` (копия из репо) и `.env` (секреты, не в git).
  В `.env` заданы `COMPOSE_FILE=docker-compose.prod.yml` и `HH_PARS_IMAGE` — поэтому
  `docker compose ps/logs/up` там работают без `-f`;
- Telegram — напрямую (WARP, как на старом сервере, не нужен);
- hh.ru — через SOCKS5 RU-ноды: `HH_PROXY_URL=socks5://17.9.7.5:1080` (доступ с главного узла
  разрешён на стороне ноды);
- `deploy.sh` — копия [deploy/server-deploy.sh](deploy/server-deploy.sh) в `/root/scripts/hh-pars/`,
  принудительная команда ключа деплоя в `authorized_keys` (`command=…,restrict`): ключ из
  GitHub не даёт shell и умеет только обновить образ сервиса `bot`. Журнал — `deploy.log` рядом.

Что обновляет CD, а что — руками:

- образ бота — CD;
- `docker-compose.prod.yml` и `.env` — руками (скопировать на сервер, `docker compose up -d`);
- сам `deploy.sh` — руками (CD его не трогает).

Откат на прежний образ (они остаются на диске):

```bash
cd /root/hh-pars
sed -i 's|^HH_PARS_IMAGE=.*|HH_PARS_IMAGE=ghcr.io/ggwolst/hh-pars:<sha>|' .env
docker compose up -d bot
```

Подробности и откат всей установки — `/root/scripts/hh-pars/README.md` на сервере.
