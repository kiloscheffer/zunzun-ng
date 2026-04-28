# Linux deployment

Tested configuration: Ubuntu 22.04 / 24.04 LTS. Adapt package names and paths for other distributions.

## System dependencies

```bash
sudo apt-get update
sudo apt-get install -y python3-venv nginx

# uv installer (pick one):
curl -LsSf https://astral.sh/uv/install.sh | sh
# or: sudo apt-get install pipx && pipx install uv
```

## Site installation

```bash
sudo mkdir -p /var/www/zunzun-ng
sudo chown "$USER":www-data /var/www/zunzun-ng
cd /var/www/zunzun-ng
git clone https://github.com/kiloscheffer/zunzun-ng.git .
uv sync --no-dev
uv run python manage.py migrate
```

`migrate` creates `session_db/db.sqlite3` (gitignored) and applies the `sessions.0001_initial` migration. Without it, the first session write from a forked child fails because `django_session` doesn't exist.

Ensure the service account (`www-data` below) owns `temp/` and `session_db/` so the child processes can write there:

```bash
sudo chown -R www-data:www-data /var/www/zunzun-ng/temp /var/www/zunzun-ng/session_db
```

## Stack A (recommended): nginx → Waitress

Waitress is the cross-platform WSGI server. Its thread-based worker model plays nicely with the site's `multiprocessing.Process(spawn)` fit architecture. Uses the same command on Linux, macOS, and Windows.

### systemd unit

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
# Allow the service account to reach uv-managed Python
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
```

### nginx config

Write `/etc/nginx/sites-available/zunzun-ng`:

```nginx
server {
    listen 80;
    server_name zunzun-ng.example.com;

    # Serve committed static assets directly (bypasses Waitress for performance)
    location /static/ {
        alias /var/www/zunzun-ng/static/;
        expires 7d;
    }

    # Serve runtime-generated files (PDFs, plots, animations) directly too.
    # These are written by spawned fit children and don't need Waitress'
    # request handling.
    location /temp/ {
        alias /var/www/zunzun-ng/temp/;
        expires 1h;
    }

    # Serve vendored "Common Problems" static content directly.
    location /commonproblems/ {
        alias /var/www/zunzun-ng/commonproblems/;
        expires 7d;
    }

    # Pass everything else to Waitress
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # Fits can take minutes; don't time out the proxy
        proxy_read_timeout 600s;
    }
}
```

Enable:

```bash
sudo ln -s /etc/nginx/sites-available/zunzun-ng /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

For TLS: `sudo certbot --nginx -d zunzun-ng.example.com`.

## Stack B (alternate): nginx → gunicorn

`gunicorn` is still supported on Linux for sites that already run it. **Critical constraint:** sync workers only.

```bash
uv add gunicorn  # or include in pyproject.toml
uv run gunicorn \
    --workers 4 \
    --worker-class sync \
    --threads 1 \
    --bind 127.0.0.1:8000 \
    --timeout 600 \
    wsgi:application
```

**Do NOT use `--worker-class gthread` or `--threads > 1`.** The site's view code spawns `multiprocessing.Process` children; inside a multi-threaded gunicorn worker, the parent's inherited Python locks cause deadlocks when the spawn child re-imports Django. This is exactly the hazard §4.1 of the design spec moved from fork-safe to spawn-safe.

Apache + mod_wsgi works with the same constraint: `WSGIDaemonProcess threads=1`.

## Operational notes

- **Fit runtime:** typical 2D polynomial quadratic completes in ~10–30 s on a modern 8-core box. Function-finder runs over many equations can take minutes.
- **Housekeeping:** `HomePageView` spawns a daemon child on every home-page load to trim `temp/` when it exceeds `MAX_TEMP_DIR_SIZE_IN_MBYTES` (default 500 in `settings.py`) and to purge expired sessions.
- **Child-process visibility:** during a fit, `ps aux | grep python` shows `waitress-serve` + the spawned `_run_fit_child` + up to 4 Pool workers under Linux fork (see `get_parallel_process_count`). Configurable via passing `cpu_cap` to that function if you customize.
- **Logs:** child-process tracebacks land in `temp/{pid}.log`. Reap them periodically (cron) or rely on the temp-dir trim.

## What this recipe does NOT cover

- Multi-host deployment, horizontal scaling, session sharing — none are necessary for the site's typical load (a handful of concurrent research users).
- Database migration — the only stateful thing is `session_db/db.sqlite3`, recreated by `manage.py migrate`.
- Backups — sessions are ephemeral (5-day expiry); there's nothing long-lived to back up.
