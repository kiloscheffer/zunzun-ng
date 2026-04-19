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
sudo mkdir -p /usr/local/var/zunzunsite3
sudo chown "$USER":staff /usr/local/var/zunzunsite3
cd /usr/local/var/zunzunsite3
git clone https://bitbucket.org/zunzuncode/zunzunsite3.git .
uv sync --no-dev
uv run python manage.py migrate
```

## launchd plist

Write `~/Library/LaunchAgents/com.zunzunsite3.waitress.plist` (user-level) or `/Library/LaunchDaemons/com.zunzunsite3.waitress.plist` (system-level):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.zunzunsite3.waitress</string>

    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/var/zunzunsite3/.venv/bin/waitress-serve</string>
        <string>--listen=127.0.0.1:8000</string>
        <string>wsgi:application</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/usr/local/var/zunzunsite3</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/usr/local/var/zunzunsite3/waitress.log</string>

    <key>StandardErrorPath</key>
    <string>/usr/local/var/zunzunsite3/waitress.err</string>
</dict>
</plist>
```

Load:

```bash
launchctl load ~/Library/LaunchAgents/com.zunzunsite3.waitress.plist
launchctl start com.zunzunsite3.waitress
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
  launchctl stop com.zunzunsite3.waitress
  launchctl start com.zunzunsite3.waitress
  ```
- **Logs:** `/usr/local/var/zunzunsite3/waitress.log` and `waitress.err`.
- **No Defender equivalent required.** macOS's XProtect doesn't scan `.venv/` aggressively the way Windows Defender does.

## Verification required

Before relying on this recipe in production, a macOS maintainer should:

1. Run `scripts/smoke_test.py` against a freshly-installed macOS box and confirm `SMOKE OK`.
2. Confirm the launchd plist actually starts Waitress at boot (`launchctl list | grep zunzunsite3`).
3. Confirm nginx reverse-proxy serves static files and forwards to Waitress.
4. Report findings back into this doc by removing the "verification status" banner at the top.
