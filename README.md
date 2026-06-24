# LaptopSentinel 🛰️

> A self-hosted laptop tracking dashboard built with Python (Flask) + a lightweight cross-platform agent.

Track your laptops online, get notified the moment they connect to the internet, and remotely lock, message, or shut them down — all from a sleek mobile-responsive web dashboard.

---

## Screenshots

```
┌─────────────────────────────────────────────────────┐
│  🖥  LaptopSentinel          [Devices][Events][...]  │
├────────────┬────────────┬────────────┬───────────────┤
│ Total: 3   │ Online: 2  │ Offline: 1 │ Last Alert    │
├─────────────────────────────────────────────────────┤
│ ● MacBook Pro          [ONLINE]                      │
│   192.168.1.45 · Amsterdam, NL                       │
│   Battery: 74% ⚡  |  Last seen: just now            │
│   [Lock] [Message] [Screenshot] [Shutdown]           │
└─────────────────────────────────────────────────────┘
```

---

## Features

| Feature | Details |
|---|---|
| 🔔 Connect notification | Logs an alert the instant a laptop comes online |
| 📍 IP geolocation | Auto-detects city, country, ISP — no GPS required |
| 🔒 Remote lock | Lock the screen within one heartbeat cycle (≤60s) |
| 💬 Remote message | Pop up a dialog on the laptop screen |
| ⏻ Remote shutdown | Graceful OS-level shutdown |
| 📸 Screenshot | Capture the screen remotely |
| 🔋 Battery status | Percentage + charging state |
| 📡 Offline detection | Device marked offline after 3 min without heartbeat |
| 📱 Mobile responsive | Full bottom-nav UI on phones and tablets |
| 🔐 Auth | Password-protected session-based login |

---

## Project Structure

```
laptop-tracker/
├── app.py                  ← Flask server: REST API + session auth
├── requirements.txt        ← Python dependencies
├── tracker_data.json       ← Auto-created on first run (device/event store)
├── templates/
│   └── dashboard.html      ← Single-file responsive web dashboard
├── agent/
│   └── agent.py            ← Lightweight agent — runs on tracked laptops
└── README.md               ← This file
```

---

## Quick Start

### Prerequisites

- Python 3.8+
- pip

### 1. Start the Server

Run this on any always-on machine (home server, VPS, Raspberry Pi, etc.):

```bash
git clone <your-repo> laptop-tracker
cd laptop-tracker
pip install -r requirements.txt
python app.py
```

The dashboard will be at **http://localhost:5000**

> **Default password:** `admin123` — change it immediately in Settings.

### 2. Deploy the Agent

Copy `agent/agent.py` to each laptop you want to track, then run:

```bash
pip install requests psutil
python agent.py --server http://YOUR_SERVER_IP:5000
```

The agent will appear as a device in the dashboard within seconds.

### 3. Auto-Start the Agent on Boot

**Windows** — Create `start_tracker.bat` and add it to Task Scheduler (run at logon):
```bat
@echo off
start /min python C:\tracker\agent.py --server http://YOUR_SERVER:5000
```

**macOS** — Add a LaunchAgent plist at `~/Library/LaunchAgents/com.tracker.agent.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "...">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.tracker.agent</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/opt/tracker/agent.py</string>
    <string>--server</string>
    <string>http://YOUR_SERVER:5000</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
```
Then: `launchctl load ~/Library/LaunchAgents/com.tracker.agent.plist`

**Linux** — Add to crontab (`crontab -e`):
```
@reboot python3 /opt/tracker/agent.py --server http://YOUR_SERVER:5000 &
```

---

## How It Works

```
Laptop (agent.py)                    Server (app.py)
      │                                    │
      │── POST /api/checkin ──────────────>│  On startup: sends hostname,
      │   { hostname, IP, location,        │  platform, IP, battery, location
      │     platform, battery, MAC }       │
      │                                    │  Logs "connected" event
      │<── { commands: [] } ───────────────│  Returns any pending commands
      │                                    │
      │── POST /api/heartbeat ────────────>│  Every 60s: lightweight ping
      │<── { commands: [...] } ────────────│  Returns pending commands
      │                                    │
      │── POST /api/command_result ───────>│  After executing a command,
      │   { command: "lock", result: "ok"} │  reports result back
```

---

## Remote Commands

Commands are queued on the server and delivered to the agent on its next heartbeat (within 60 seconds).

| Command | Effect |
|---|---|
| `lock` | Locks the screen (Windows/macOS/Linux) |
| `message` | Displays a popup dialog with custom text |
| `screenshot` | Captures the screen, saves to `/tmp/` |
| `shutdown` | Initiates OS graceful shutdown |
| `wipe_confirm` | Data wipe — not active in demo; extend as needed |

---

## Adding Real Email Notifications

In `app.py`, replace the placeholder notification block with:

```python
import smtplib
from email.mime.text import MIMEText

def send_email_alert(to_email, device):
    loc = device.get('location', {})
    location_str = f"{loc.get('city','')}, {loc.get('country','')}"
    body = (
        f"Device '{device['hostname']}' just came online.\n\n"
        f"IP Address : {device['ip_address']}\n"
        f"Location   : {location_str}\n"
        f"Platform   : {device['platform']}\n"
        f"User       : {device['username']}\n"
    )
    msg = MIMEText(body)
    msg['Subject'] = f"[LaptopSentinel] {device['hostname']} connected"
    msg['From'] = 'your@gmail.com'
    msg['To'] = to_email

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login('your@gmail.com', 'YOUR_APP_PASSWORD')
        server.send_message(msg)
```

> Use a [Gmail App Password](https://support.google.com/accounts/answer/185833) — not your main password.

---

## Production Deployment (nginx + HTTPS)

For a public-facing server, always use HTTPS:

```nginx
server {
    listen 443 ssl;
    server_name tracker.yourdomain.com;

    ssl_certificate     /etc/letsencrypt/live/tracker.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/tracker.yourdomain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

Run with gunicorn instead of the dev server:
```bash
pip install gunicorn
gunicorn -w 2 -b 127.0.0.1:5000 app:app
```

---

## API Reference

### Agent Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/checkin` | POST | Full check-in with device info, location, battery |
| `/api/heartbeat` | POST | Lightweight ping; returns pending commands |
| `/api/command_result` | POST | Agent reports result of an executed command |

### Dashboard Endpoints (requires login)

| Endpoint | Method | Description |
|---|---|---|
| `/api/devices` | GET | List all registered devices |
| `/api/events` | GET | Event log (last 50); filter by `?device_id=` |
| `/api/command` | POST | Queue a command for a device |
| `/api/settings` | GET/POST | Read or update notification settings |
| `/api/remove_device` | POST | Remove a device from the dashboard |
| `/api/login` | POST | Authenticate and start a session |
| `/api/logout` | POST | End session |

---

## Security Notes

- **Change the default password** (`admin123`) immediately after first login
- The agent communicates **outbound only** — no inbound ports needed on the laptop
- Geolocation uses [ipapi.co](https://ipapi.co) — only the laptop's public IP is shared
- All data is stored locally in `tracker_data.json` — nothing leaves your server
- For production use, always run behind HTTPS (see nginx section above)

---

## Extending the Project

Some ideas to build on top of this:

- **Map view** — plot device locations using Leaflet.js + the lat/lng from geolocation
- **Screenshot uploads** — extend the agent to POST the screenshot bytes back to the server
- **Geofence alerts** — trigger alerts when a device leaves a defined area
- **Multi-user auth** — add user accounts with per-device permissions
- **SMS alerts** — integrate Twilio for SMS in addition to email
- **Database** — swap `tracker_data.json` for SQLite or PostgreSQL for scale

---

## License

MIT — use freely for personal or commercial projects.
