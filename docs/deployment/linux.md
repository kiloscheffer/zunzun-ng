# Linux deployment

Tested configuration: Ubuntu 22.04 / 24.04 LTS. Adapt package names and paths for other distributions.

## System dependencies

```bash
sudo apt-get update
sudo apt-get install -y python3-venv nginx imagemagick gifsicle

# uv installer (pick one):
curl -LsSf https://astral.sh/uv/install.sh | sh
# or: sudo apt-get install pipx && pipx install uv
```

Verify `mogrify` and `gifsicle` are on `PATH`:

```bash
which magick  # or: which mogrify
which gifsicle
```

If either is missing, `imagemagick` / `gifsicle` isn't installed correctly; the site will log a prominent warning on startup and animated GIF output will fail (fits and PDFs still work).

## Site installation

```bash
sudo mkdir -p /var/www/zunzunsite3
sudo chown "$USER":www-data /var/www/zunzunsite3
cd /var/www/zunzunsite3
git clone https://bitbucket.org/zunzuncode/zunzunsite3.git .
uv sync --no-dev
uv run python manage.py migrate
```

`migrate` creates `session_db/db.sqlite3` (gitignored) and applies the `sessions.0001_initial` migration. Without it, the first session write from a forked child fails because `django_session` doesn't exist.

Ensure the service account (`www-data` below) owns `temp/` and `session_db/` so the child processes can write there:

```bash
sudo chown -R www-data:www-data /var/www/zunzunsite3/temp /var/www/zunzunsite3/session_db
```

## Stack A (recommended): nginx → Waitress

Waitress is the cross-platform WSGI server. Its thread-based worker model plays nicely with the site's `multiprocessing.Process(spawn)` fit architecture. Uses the same command on Linux, macOS, and Windows.

### systemd unit

Write `/etc/systemd/system/zunzunsite3.service`:

```ini
[Unit]
Description=ZunZunSite3 (Waitress)
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/var/www/zunzunsite3
ExecStart=/var/www/zunzunsite3/.venv/bin/waitress-serve --listen=127.0.0.1:8000 wsgi:application
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal
# Allow the service account to reach uv-managed Python
Environment=PATH=/var/www/zunzunsite3/.venv/bin:/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now zunzunsite3
sudo systemctl status zunzunsite3
```

Logs:

```bash
sudo journalctl -u zunzunsite3 -f
```

### nginx config

Write `/etc/nginx/sites-available/zunzunsite3`:

```nginx
server {
    listen 80;
    server_name zunzunsite3.example.com;

    # Serve static files directly (bypasses Waitress for performance)
    location /temp/static_images/ {
        alias /var/www/zunzunsite3/temp/static_images/;
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
sudo ln -s /etc/nginx/sites-available/zunzunsite3 /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

For TLS: `sudo certbot --nginx -d zunzunsite3.example.com`.

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
