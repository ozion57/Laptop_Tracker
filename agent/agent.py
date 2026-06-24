#!/usr/bin/env python3
"""
Laptop Tracker Agent
===================
Run this on the laptop you want to track.
It checks in with the server on connect and every 60 seconds.

Usage:
    python agent.py --server http://YOUR_SERVER:5000 --device-id MY_LAPTOP

Auto-start on boot:
    Windows: Add to Task Scheduler or Startup folder
    macOS:   Add as a LaunchAgent plist
    Linux:   Add to crontab: @reboot python3 /path/to/agent.py &
"""

import argparse
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime

try:
    import requests
except ImportError:
    print("Installing requests...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

# ── Config ────────────────────────────────────────────────────────────────────
DEFAULT_SERVER = "http://localhost:5000"
CHECKIN_INTERVAL = 60   # seconds
CONFIG_FILE = os.path.join(os.path.dirname(__file__), ".tracker_config.json")

# ── Device Info ───────────────────────────────────────────────────────────────
def get_device_id(custom_id=None):
    """Stable unique ID for this device."""
    if custom_id:
        return custom_id
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
            if "device_id" in cfg:
                return cfg["device_id"]
    # Generate from MAC + hostname for stability
    raw = f"{socket.gethostname()}-{uuid.getnode()}"
    device_id = hashlib.md5(raw.encode()).hexdigest()[:12]
    with open(CONFIG_FILE, "w") as f:
        json.dump({"device_id": device_id}, f)
    return device_id

def get_mac_address():
    try:
        mac = ':'.join(f'{(uuid.getnode() >> i) & 0xff:02x}' for i in range(0, 48, 8)[::-1])
        return mac
    except:
        return "unknown"

def get_battery():
    try:
        import psutil
        b = psutil.sensors_battery()
        if b:
            return {"percent": round(b.percent), "plugged": b.power_plugged}
    except:
        pass
    return None

def get_location():
    """Get approximate location from IP geolocation (no GPS needed)."""
    try:
        r = requests.get("https://ipapi.co/json/", timeout=5)
        data = r.json()
        return {
            "city": data.get("city", ""),
            "region": data.get("region", ""),
            "country": data.get("country_name", ""),
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
            "isp": data.get("org", ""),
            "timezone": data.get("timezone", ""),
        }
    except:
        return {}

def build_payload(device_id):
    return {
        "device_id": device_id,
        "hostname": socket.gethostname(),
        "platform": f"{platform.system()} {platform.release()}",
        "username": os.getenv("USERNAME") or os.getenv("USER") or "unknown",
        "mac_address": get_mac_address(),
        "battery": get_battery(),
        "location": get_location(),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

# ── Command Execution ─────────────────────────────────────────────────────────
def execute_command(cmd_obj, server, device_id):
    cmd = cmd_obj.get("command")
    args = cmd_obj.get("args", {})
    result = "unknown"

    print(f"[!] Executing command: {cmd}")

    try:
        if cmd == "lock":
            system = platform.system()
            if system == "Windows":
                os.system("rundll32.exe user32.dll,LockWorkStation")
            elif system == "Darwin":
                os.system('/System/Library/CoreServices/Menu\ Extras/User.menu/Contents/Resources/CGSession -suspend')
            elif system == "Linux":
                os.system("loginctl lock-session")
            result = "locked"

        elif cmd == "shutdown":
            system = platform.system()
            if system == "Windows":
                os.system("shutdown /s /t 10")
            else:
                os.system("sudo shutdown -h now")
            result = "shutdown initiated"

        elif cmd == "message":
            msg = args.get("text", "Message from admin")
            system = platform.system()
            if system == "Windows":
                os.system(f'msg * "{msg}"')
            elif system == "Darwin":
                os.system(f'osascript -e \'display dialog "{msg}" with title "System Alert"\'')
            elif system == "Linux":
                os.system(f'notify-send "System Alert" "{msg}"')
            result = "message_displayed"

        elif cmd == "screenshot":
            try:
                import subprocess
                fname = f"/tmp/screenshot_{int(time.time())}.png"
                system = platform.system()
                if system == "Windows":
                    subprocess.run(["powershell", "-command",
                        f'Add-Type -AssemblyName System.Windows.Forms;[System.Windows.Forms.Screen]::PrimaryScreen | ForEach-Object {{ $bmp = New-Object System.Drawing.Bitmap($_.Bounds.Width,$_.Bounds.Height); $g = [System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($_.Bounds.Location,[System.Drawing.Point]::Empty,$_.Bounds.Size); $bmp.Save("{fname}") }}'],
                        capture_output=True)
                elif system == "Darwin":
                    subprocess.run(["screencapture", "-x", fname])
                elif system == "Linux":
                    subprocess.run(["scrot", fname])
                result = f"screenshot_saved:{fname}"
            except Exception as e:
                result = f"screenshot_failed:{e}"

        elif cmd == "wipe_confirm":
            # DANGEROUS — only runs if server sends explicit wipe confirmation
            result = "wipe_not_implemented_in_demo"

    except Exception as e:
        result = f"error: {e}"

    # Report result back to server
    try:
        requests.post(f"{server}/api/command_result", json={
            "device_id": device_id,
            "command": cmd,
            "result": result,
        }, timeout=10)
    except:
        pass

# ── Main Loop ─────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Laptop Tracker Agent")
    parser.add_argument("--server", default=DEFAULT_SERVER, help="Tracker server URL")
    parser.add_argument("--device-id", default=None, help="Custom device ID")
    parser.add_argument("--interval", type=int, default=CHECKIN_INTERVAL)
    args = parser.parse_args()

    device_id = get_device_id(args.device_id)
    server = args.server.rstrip("/")

    print(f"[+] Laptop Tracker Agent")
    print(f"    Device ID : {device_id}")
    print(f"    Server    : {server}")
    print(f"    Hostname  : {socket.gethostname()}")
    print(f"    Interval  : {args.interval}s")
    print()

    first_run = True

    while True:
        try:
            if first_run:
                # Full check-in with location on startup
                payload = build_payload(device_id)
                r = requests.post(f"{server}/api/checkin", json=payload, timeout=15)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Check-in OK  (IP location fetched)")
                first_run = False
            else:
                # Lightweight heartbeat
                r = requests.post(f"{server}/api/heartbeat",
                                  json={"device_id": device_id}, timeout=10)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Heartbeat OK")

            if r.ok:
                response = r.json()
                for cmd in response.get("commands", []):
                    execute_command(cmd, server, device_id)

        except requests.exceptions.ConnectionError:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Offline — will retry in {args.interval}s")
            first_run = True  # Force full check-in when back online

        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Error: {e}")

        time.sleep(args.interval)

if __name__ == "__main__":
    main()
