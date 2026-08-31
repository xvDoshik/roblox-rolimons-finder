[EN](../README.md) | RU

# Rolimons Owner Finder

![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white)


Веб-инструмент и API для поиска игроков Roblox, у которых есть все указанные limited с Rolimons.

Production: https://finder.usd.cheap

## Структура

```
rolimons-owner-finder/
  server.py          FastAPI app
  service.py         Rolimons parsing and intersection logic
  sanitizer.py       Input/output sanitization
  security.py        Rate limit and middleware
  cli.py             Command-line interface
  web/               Frontend static files
  deploy/            systemd and nginx templates
```

## Локальный запуск

```bash
./run.sh
```

Открой http://127.0.0.1:8787

## CLI

```bash
python3 cli.py 188004500 553971858 553970961 --json
```

## API

- `GET /api/health`
- `POST /api/intersect`

```json
{
  "items": ["188004500", "553971858"]
}
```

## Деплой

```bash
rsync -av --exclude venv --exclude .git ./ user@host:/opt/rolimons-owner-finder/
ssh user@host '
  cd /opt/rolimons-owner-finder
  python3 -m venv venv
  venv/bin/pip install -r requirements.txt
  cp deploy/rolimons-finder.service /etc/systemd/system/
  cp deploy/finder.usd.cheap.nginx /etc/nginx/sites-available/finder.usd.cheap
  systemctl daemon-reload
  systemctl enable --now rolimons-finder
  nginx -t && systemctl reload nginx
  certbot --nginx -d finder.usd.cheap
'
```

## Переменные окружения

- `ALLOWED_ORIGINS` - CORS origins через запятую
