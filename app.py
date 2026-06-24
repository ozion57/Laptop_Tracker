"""
Laptop Tracker - Flask Backend
Handles: device check-in, geolocation, notifications, remote commands
"""

from flask import Flask, request, jsonify, render_template, session
from flask_cors import CORS
import json, os, time, hashlib, secrets
from datetime import datetime
from collections import defaultdict

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
CORS(app)

# ── Data Storage (file-based, no DB needed for demo) ─────────────────────────
DATA_FILE = "tracker_data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return {
        "devices": {},
        "events": [],
        "commands": {},   # device_id -> list of pending commands
        "settings": {
            "notify_email": "",
            "notify_on_connect": True,
            "admin_password_hash": hashlib.sha256(b"admin123").hexdigest()
        }
    }

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def log_event(data, device_id, event_type, detail=""):
    data["events"].insert(0, {
        "id": secrets.token_hex(4),
        "device_id": device_id,
        "type": event_type,
        "detail": detail,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    })
    data["events"] = data["events"][:200]  # keep last 200

# ── Agent Endpoints (called by the laptop agent) ──────────────────────────────

@app.route("/api/checkin", methods=["POST"])
def checkin():
    """Agent calls this on startup and periodically."""
    payload = request.get_json(silent=True) or {}
    device_id = payload.get("device_id", "")
    if not device_id:
        return jsonify({"error": "missing device_id"}), 400

    # Get real IP (works behind proxy too)
    ip = request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip()

    data = load_data()

    is_new = device_id not in data["devices"]
    was_offline = data["devices"].get(device_id, {}).get("status") == "offline"

    now = datetime.utcnow().isoformat() + "Z"
    device = data["devices"].get(device_id, {})
    device.update({
        "device_id": device_id,
        "hostname": payload.get("hostname", "Unknown"),
        "platform": payload.get("platform", "Unknown"),
        "username": payload.get("username", "Unknown"),
        "ip_address": ip,
        "location": payload.get("location", {}),
        "status": "online",
        "last_seen": now,
        "first_seen": device.get("first_seen", now),
        "battery": payload.get("battery", None),
        "mac_address": payload.get("mac_address", ""),
    })
    data["devices"][device_id] = device

    # Log connect event
    if is_new or was_offline:
        log_event(data, device_id, "connected",
                  f"Device came online from IP {ip}")

        # Simulate email notification (in production: use smtplib or SendGrid)
        if data["settings"].get("notify_on_connect") and data["settings"].get("notify_email"):
            log_event(data, device_id, "notification_sent",
                      f"Alert sent to {data['settings']['notify_email']}")

    save_data(data)

    # Return pending commands
    cmds = data["commands"].get(device_id, [])
    data["commands"][device_id] = []
    save_data(data)

    return jsonify({"commands": cmds, "server_time": now})


@app.route("/api/command_result", methods=["POST"])
def command_result():
    """Agent reports result of executed command."""
    payload = request.get_json(silent=True) or {}
    device_id = payload.get("device_id", "")
    data = load_data()
    log_event(data, device_id, "command_result",
              f"{payload.get('command','?')}: {payload.get('result','')}")
    save_data(data)
    return jsonify({"ok": True})


@app.route("/api/heartbeat", methods=["POST"])
def heartbeat():
    """Lightweight ping every 60s to maintain online status."""
    payload = request.get_json(silent=True) or {}
    device_id = payload.get("device_id", "")
    if not device_id:
        return jsonify({"ok": False}), 400

    data = load_data()
    if device_id in data["devices"]:
        data["devices"][device_id]["last_seen"] = datetime.utcnow().isoformat() + "Z"
        data["devices"][device_id]["status"] = "online"
        save_data(data)

    cmds = data["commands"].get(device_id, [])
    data["commands"][device_id] = []
    save_data(data)
    return jsonify({"commands": cmds})


# ── Dashboard API (called by the web UI) ──────────────────────────────────────

@app.route("/api/login", methods=["POST"])
def login():
    payload = request.get_json(silent=True) or {}
    pw = payload.get("password", "")
    data = load_data()
    if hashlib.sha256(pw.encode()).hexdigest() == data["settings"]["admin_password_hash"]:
        session["auth"] = True
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Invalid password"}), 401

@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})

def require_auth():
    return session.get("auth") == True

@app.route("/api/devices", methods=["GET"])
def get_devices():
    if not require_auth():
        return jsonify({"error": "Unauthorized"}), 401
    data = load_data()
    # Mark devices offline if not seen in 3 min
    now = time.time()
    for d in data["devices"].values():
        last = d.get("last_seen", "")
        try:
            ts = datetime.fromisoformat(last.replace("Z",""))
            diff = now - ts.timestamp()
            if diff > 180:
                d["status"] = "offline"
        except:
            pass
    return jsonify(list(data["devices"].values()))

@app.route("/api/events", methods=["GET"])
def get_events():
    if not require_auth():
        return jsonify({"error": "Unauthorized"}), 401
    data = load_data()
    device_id = request.args.get("device_id")
    events = data["events"]
    if device_id:
        events = [e for e in events if e["device_id"] == device_id]
    return jsonify(events[:50])

@app.route("/api/command", methods=["POST"])
def send_command():
    if not require_auth():
        return jsonify({"error": "Unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    device_id = payload.get("device_id", "")
    cmd = payload.get("command", "")
    if not device_id or not cmd:
        return jsonify({"error": "Missing fields"}), 400

    ALLOWED = {"lock", "shutdown", "wipe_confirm", "message", "screenshot"}
    if cmd not in ALLOWED:
        return jsonify({"error": "Unknown command"}), 400

    data = load_data()
    if device_id not in data["commands"]:
        data["commands"][device_id] = []
    data["commands"][device_id].append({
        "command": cmd,
        "args": payload.get("args", {}),
        "issued_at": datetime.utcnow().isoformat() + "Z"
    })
    log_event(data, device_id, "command_issued", f"Command: {cmd}")
    save_data(data)
    return jsonify({"ok": True})

@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    if not require_auth():
        return jsonify({"error": "Unauthorized"}), 401
    data = load_data()
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        if "notify_email" in payload:
            data["settings"]["notify_email"] = payload["notify_email"]
        if "notify_on_connect" in payload:
            data["settings"]["notify_on_connect"] = payload["notify_on_connect"]
        if "new_password" in payload and payload["new_password"]:
            data["settings"]["admin_password_hash"] = \
                hashlib.sha256(payload["new_password"].encode()).hexdigest()
        save_data(data)
        return jsonify({"ok": True})
    s = data["settings"].copy()
    del s["admin_password_hash"]
    return jsonify(s)

@app.route("/api/remove_device", methods=["POST"])
def remove_device():
    if not require_auth():
        return jsonify({"error": "Unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    device_id = payload.get("device_id", "")
    data = load_data()
    data["devices"].pop(device_id, None)
    log_event(data, device_id, "device_removed", "Removed from dashboard")
    save_data(data)
    return jsonify({"ok": True})

# ── Dashboard UI ──────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("dashboard.html")

if __name__ == "__main__":
    app.run(debug=True, port=5000)
