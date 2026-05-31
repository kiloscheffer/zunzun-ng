# macOS deployment

**Verification status:** Author had no Mac hardware available during
the April 2026 cross-platform migration. The Waitress and Caddy
commands below are written by structural extension from the Linux
recipe. **Verify on a real macOS box before relying on this recipe.**

## System dependencies

```bash
# Homebrew package manager (if not already installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# uv (Python package manager)
brew install uv

# Caddy
brew install caddy
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

`migrate` creates `session_db/db.sqlite3` and applies both
`sessions.0001_initial` and the `zunzun` app migrations (including
the `zunzun_lrpstatus` status-tracking table). No extra command needed.

## Caddyfile

Copy [`Caddyfile.example`](Caddyfile.example) to
`/usr/local/etc/Caddyfile` (Homebrew's default location) and adjust
the hostname + paths to match `/usr/local/var/zunzun-ng/`:

```bash
sudo cp /usr/local/var/zunzun-ng/docs/deployment/Caddyfile.example /usr/local/etc/Caddyfile
sudo nano /usr/local/etc/Caddyfile  # change hostname; replace /var/www/zunzun-ng with /usr/local/var/zunzun-ng
brew services start caddy
brew services list  # verify caddy is running
```

Caddy obtains and renews Let's Encrypt certs automatically as long as
the hostname resolves to the machine and ports 80 + 443 are open.

## launchd plist for Waitress

Write `~/Library/LaunchAgents/com.zunzun-ng.waitress.plist` (user-level)
or `/Library/LaunchDaemons/com.zunzun-ng.waitress.plist` (system-level):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
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

Load and start:

```bash
launchctl load ~/Library/LaunchAgents/com.zunzun-ng.waitress.plist
launchctl start com.zunzun-ng.waitress
launchctl list | grep zunzun-ng
```

## Operational notes

- **Logs:**
  - Caddy: `brew services log caddy` or `~/Library/Logs/Homebrew/caddy/caddy.log`.
  - Waitress: `/usr/local/var/zunzun-ng/waitress.log` and `waitress.err`.
  - Child-process tracebacks: `temp/{pid}.log`.
- **Restart Waitress after deploys:**

  ```bash
  launchctl stop com.zunzun-ng.waitress
  launchctl start com.zunzun-ng.waitress
  ```

- **Verify Caddy is running:** `brew services list` shows status.

## Verification

After both services are running, visit `https://<your-hostname>/` in a
browser. Caddy provisions certs on first request, which can take a
few seconds. Check Caddy logs for any cert-acquisition errors:

```bash
brew services log caddy
```

## What this recipe does NOT cover

- Per-user vs system-wide installation choice — see Apple's launchd
  documentation for the trade-offs (LaunchAgents run on user login;
  LaunchDaemons run at boot before any user logs in).
- Confirming that the launchd plist actually starts Waitress at
  boot (`launchctl list | grep zunzun-ng`).
