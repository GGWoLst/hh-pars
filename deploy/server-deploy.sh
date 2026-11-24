#!/bin/bash
# Деплой hh-pars из GitHub Actions (.github/workflows/cd.yml, job deploy).
# На сервере лежит как /root/scripts/hh-pars/deploy.sh и стоит принудительной
# командой ключа в /root/.ssh/authorized_keys (command="…/deploy.sh",restrict):
# ключ из секретов GitHub умеет только это — обновить образ сервиса bot.
#
# Принимает в SSH_ORIGINAL_COMMAND ровно:
#   deploy <образ> <пользователь GitHub> <токен GHCR на время запуска>
#   образ — ghcr.io/ggwolst/hh-pars:<sha 40 hex> | :latest
#
# Откат (токен не нужен, прежние образы остаются на диске):
#   cd /root/hh-pars && sed -i 's|^HH_PARS_IMAGE=.*|HH_PARS_IMAGE=<прежний образ>|' .env && docker compose up -d bot
set -euo pipefail
APP=/root/hh-pars
LOG=/root/scripts/hh-pars/deploy.log

read -r verb image user token extra <<< "${SSH_ORIGINAL_COMMAND:-}"
if [ "${verb:-}" != deploy ] || [ -z "${token:-}" ] || [ -n "${extra:-}" ]; then
  echo "отказ: разрешена только команда «deploy <образ> <пользователь> <токен>»" >&2
  exit 1
fi
if ! [[ "$image" =~ ^ghcr\.io/ggwolst/hh-pars:([0-9a-f]{40}|latest)$ ]]; then
  echo "отказ: образ не из ghcr.io/ggwolst/hh-pars: $image" >&2
  exit 1
fi
if ! [[ "$user" =~ ^[A-Za-z0-9-]{1,39}(\[bot\])?$ ]]; then
  echo "отказ: недопустимое имя пользователя" >&2
  exit 1
fi

exec > >(tee -a "$LOG") 2>&1
echo "=== $(date '+%F %T') деплой $image"
cd "$APP"
trap 'docker logout ghcr.io >/dev/null 2>&1 || true' EXIT
printf '%s' "$token" | docker login ghcr.io -u "$user" --password-stdin >/dev/null
export HH_PARS_IMAGE="$image"
docker compose pull -q bot
docker compose up -d --no-build bot
# Запоминаем образ в .env, чтобы ручной `docker compose up -d` не вернул старый.
sed -i "s|^HH_PARS_IMAGE=.*|HH_PARS_IMAGE=$image|" .env
echo "$image" > .deployed-image
docker image prune -f >/dev/null
docker compose ps bot --format '{{.Name}}  {{.Image}}  {{.Status}}'
