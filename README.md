# hh-pars

Каркас Telegram-бота, который парсит вакансии с hh.ru API и присылает новые в чат.

Стек: Python 3.12, aiogram 3, httpx, SQLAlchemy (async) + PostgreSQL, APScheduler, Docker.

## Структура

```
src/
  config.py        # настройки из .env (pydantic-settings)
  hh_client.py      # клиент к api.hh.ru
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
- `PARSE_INTERVAL_MINUTES`, `HH_SEARCH_TEXT`, `HH_SEARCH_AREA` — параметры парсинга.

## CI/CD

### CI (`.github/workflows/ci.yml`)

На каждый push/PR в `main`: линт (ruff), тесты (pytest), пробная сборка Docker-образа.
Выполняется на обычных github-hosted раннерах, публикации никуда не делает.

### CD (`.github/workflows/cd.yml`)

Шаблон без привязки к конкретному хостингу. Собирает и пушит образ в GHCR, затем деплоит.

## Как задеплоить в локальную сеть (без белого IP / проброса портов)

GitHub-раннеры по умолчанию не имеют доступа к машинам в локальной сети, а открывать
входящие порты наружу ради деплоя — плохая идея. Рабочие варианты:

1. **Self-hosted GitHub Actions runner внутри сети (рекомендуется, уже в шаблоне).**
   Ставится агент (`actions-runner`) на машину/сервер в локальной сети, он сам открывает
   исходящее соединение к GitHub и слушает джобы. Входящих портов не требуется.
   ```bash
   # на целевой машине
   mkdir actions-runner && cd actions-runner
   curl -o actions-runner.tar.gz -L https://github.com/actions/runner/releases/latest/download/actions-runner-linux-x64.tar.gz
   tar xzf actions-runner.tar.gz
   ./config.sh --url https://github.com/OWNER/REPO --token <TOKEN> --labels self-hosted-local
   ./svc.sh install && ./svc.sh start
   ```
   Деплой-джоба в `cd.yml` (`runs-on: [self-hosted, self-hosted-local]`) выполнит
   `docker compose pull && up -d` уже локально, с прямым доступом к сети.

2. **Pull-based деплой через Watchtower (без раннера вообще).**
   На машине в локальной сети крутится [Watchtower](https://containrrr.dev/watchtower/),
   который сам поллит registry и обновляет контейнер при появлении новой версии образа.
   GitHub Actions в этом случае только собирает и пушит образ в GHCR — деплоить руками
   ничего не нужно, никакой инфраструктуры для входящих соединений не требуется:
   ```yaml
   watchtower:
     image: containrrr/watchtower
     volumes:
       - /var/run/docker.sock:/var/run/docker.sock
     command: --interval 300 hh-pars-bot
   ```

3. **VPN между GitHub-раннером и локальной сетью** (Tailscale/WireGuard action) — если
   нужен классический push-деплой (`ssh` + `docker compose`) без self-hosted раннера.
   Сложнее в настройке, обычно избыточно для одного бота — вариант 1 или 2 предпочтительнее.

Шаблон использует вариант 1. `docker-compose.prod.yml` — конфиг для целевой машины,
тянет готовый образ из GHCR вместо локальной сборки.
