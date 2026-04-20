# macOS deployment

**Verification status:** Author had no Mac hardware available during the April 2026 cross-platform migration. The Waitress command and the overall stack are the same as Linux; the launchd plist below is written by structural extension from the Linux systemd unit. **Verify on a real macOS box before relying on this recipe.**

## System dependencies

```bash
brew install python@3.14 nginx

# uv installer:
curl -LsSf https://astral.sh/uv/install.sh | sh
# or: brew install uv
```

## Site installation

```bash
sudo mkdir -p /usr/local/var/zunzun-ng
sudo chown "$USER":staff /usr/local/var/zunzun-ng
cd /usr/local/var/zunzun-ng
git clone https://github.com/kiloscheffer/zunzun-ng.git .
uv sync --no-dev
uv run python manage.py migrate
```

## launchd plist

Write `~/Library/LaunchAgents/com.zunzun-ng.waitress.plist` (user-level) or `/Library/LaunchDaemons/com.zunzun-ng.waitress.plist` (system-level):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.zunzun-ng.waitress</string>

    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/var/zunzun-ng/.venv/bin/waitress-serve</string>
        <string>--listen=127.0.0.1:8000</string>
        <string>wsgi:application</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/usr/local/var/zunzun-ng</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/usr/local/var/zunzun-ng/waitress.log</string>

    <key>StandardErrorPath</key>
    <string>/usr/local/var/zunzun-ng/waitress.err</string>
</dict>
</plist>
```

Load:

```bash
launchctl load ~/Library/LaunchAgents/com.zunzun-ng.waitress.plist
launchctl start com.zunzun-ng.waitress
```

Verify the site responds:

```bash
curl http://127.0.0.1:8000/
```

## nginx config

Same as [Linux](linux.md#nginx-config). Homebrew's nginx keeps its configuration at `/usr/local/etc/nginx/`:

- Server blocks in `/usr/local/etc/nginx/servers/` (or included from `nginx.conf`)
- `sudo brew services start nginx` to run as a system service

For TLS, Let's Encrypt via `brew install certbot` works the same as on Linux.

## Operational notes

- **Fit runtime parity:** macOS uses spawn by default on Python 3.8+ (same as Windows). Per-worker memory is similar to Windows (~750 MB), so `get_parallel_process_count` caps at 4 workers. Fits will be 2–3× slower than Linux fork on the same hardware.
- **Restart the service:**
  ```bash
  launchctl stop com.zunzun-ng.waitress
  launchctl start com.zunzun-ng.waitress
  ```
- **Logs:** `/usr/local/var/zunzun-ng/waitress.log` and `waitress.err`.
- **No Defender equivalent required.** macOS's XProtect doesn't scan `.venv/` aggressively the way Windows Defender does.

## Verification required

Before relying on this recipe in production, a macOS maintainer should:

1. Run `scripts/smoke_test.py` against a freshly-installed macOS box and confirm `SMOKE OK`.
2. Confirm the launchd plist actually starts Waitress at boot (`launchctl list | grep zunzun-ng`).
3. Confirm nginx reverse-proxy serves static files and forwards to Waitress.
4. Report findings back into this doc by removing the "verification status" banner at the top.
