# Linux deployment

Tested configuration: Ubuntu 22.04 / 24.04 LTS. Adapt package names and
paths for other distributions.

## System dependencies

```bash
sudo apt-get update
sudo apt-get install -y python3-venv

# uv installer (pick one):
curl -LsSf https://astral.sh/uv/install.sh | sh
# or: sudo apt-get install pipx && pipx install uv

# Caddy installer (Debian/Ubuntu official package):
sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt-get update
sudo apt-get install -y caddy
```

For other distros, see [caddyserver.com/docs/install](https://caddyserver.com/docs/install).

## Site installation

```bash
sudo mkdir -p /var/www/zunzun-ng
sudo chown "$USER":www-data /var/www/zunzun-ng
cd /var/www/zunzun-ng
git clone https://github.com/kiloscheffer/zunzun-ng.git .
uv sync --no-dev
uv run python manage.py migrate
```

`migrate` creates `session_db/db.sqlite3` (gitignored) and applies both
`sessions.0001_initial` and the `zunzun` app migrations. Without it, the
first session write from a spawned child fails because `django_session`
doesn't exist, and the `zunzun_lrpstatus` status-tracking table won't
exist either.

Ensure the service account (`www-data` below) owns `temp/` and
`session_db/`:

```bash
sudo chown -R www-data:www-data /var/www/zunzun-ng/temp /var/www/zunzun-ng/session_db
```

## Caddyfile

Copy [`Caddyfile.example`](Caddyfile.example) to `/etc/caddy/Caddyfile`,
edit the hostname and paths to match your install:

```bash
sudo cp /var/www/zunzun-ng/docs/deployment/Caddyfile.example /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile  # change hostname; paths above are already correct for /var/www/zunzun-ng/
sudo systemctl restart caddy
```

Verify the Caddyfile parses correctly:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
```

Caddy will obtain and renew Let's Encrypt certs automatically as long
as the hostname resolves to the server and ports 80 + 443 are open.

## systemd unit for Waitress

Write `/etc/systemd/system/zunzun-ng.service`:

```ini
[Unit]
Description=ZunZunNG (Waitress)
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/var/www/zunzun-ng
ExecStart=/var/www/zunzun-ng/.venv/bin/waitress-serve --listen=127.0.0.1:8000 wsgi:application
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal
Environment=PATH=/var/www/zunzun-ng/.venv/bin:/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now zunzun-ng
sudo systemctl status zunzun-ng
```

Logs:

```bash
sudo journalctl -u zunzun-ng -f
sudo journalctl -u caddy -f
```

## Operational notes

- **Fit runtime:** typical 2D polynomial quadratic completes in
  ~10–30 s on a modern 8-core box. Function-finder runs over many
  equations can take minutes.
- **Housekeeping:** `HomePageView` spawns a daemon child on every
  home-page load to trim `temp/` when it exceeds
  `MAX_TEMP_DIR_SIZE_IN_MBYTES` (default 500 in `settings.py`) and
  to purge expired sessions.
- **Child-process visibility:** during a fit, `ps aux | grep python`
  shows `waitress-serve` + the spawned `_run_fit_child` + up to 4
  Pool workers under Linux fork (see `get_parallel_process_count`).
- **Logs:** Waitress + Django output goes to journald. Child-process
  tracebacks land in `temp/{pid}.log` and are reaped periodically by
  the housekeeping logic.

## What this recipe does NOT cover

- Multi-host deployment, horizontal scaling, session sharing — none
  necessary for the site's typical load.
- Database migration — the only stateful thing is
  `session_db/db.sqlite3`, recreated by `manage.py migrate`.
- Backups — sessions are ephemeral (5-day expiry); generated `temp/`
  output is auto-trimmed; nothing long-lived to back up beyond the
  Caddyfile + systemd unit themselves.
