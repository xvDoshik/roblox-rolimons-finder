# Rolimons Owner Finder

Web tool and API for finding Roblox players who own all specified Rolimons limited items.

Production: https://finder.usd.cheap

## Structure

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

## Local run

```bash
./run.sh
```

Open http://127.0.0.1:8787

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

## Deploy

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

## Environment

- `ALLOWED_ORIGINS` comma-separated CORS origins
