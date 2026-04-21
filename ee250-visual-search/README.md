# EE250 — Visual Search System
HiWonder TY-900408-V3.3 + Raspberry Pi + Claude Vision

## Hardware setup

The HiWonder TY-900408-V3.3 is a USB UVC camera — plug it into any USB port on the Pi. No drivers required.

Verify it's detected:
```bash
ls /dev/video*          # should show /dev/video0
v4l2-ctl --list-devices # detailed device info
```

If you see `/dev/video2` or higher instead of `/dev/video0`, change `CAMERA_INDEX` in `stream_server.py`.

## Pi software setup

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-opencv

pip3 install flask anthropic
# if you get a permissions error: sudo pip3 install flask anthropic

# Config is already set in stream_server.py
# Just run it:
python3 pi/stream_server.py
```

The terminal will print the exact URL on startup:
```
──────────────────────────────────────────────────
  Stream live at  http://192.168.x.x:5000
  Dashboard at    http://192.168.x.x:5000/
──────────────────────────────────────────────────
```

## Accessing the dashboard

| Where | URL |
|-------|-----|
| On the Pi | `http://localhost:5000` |
| Same WiFi network | `http://<PI_IP_ADDRESS>:5000` |
| Direct stream only | `http://<PI_IP_ADDRESS>:5000/video_feed` |

## How it works (EE250 write-up)

| Step | What happens | Protocol |
|------|-------------|----------|
| 1 | Pi streams live MJPEG video to browser | HTTP `multipart/x-mixed-replace` |
| 2 | Browser captures frame every 4 seconds | JavaScript Canvas API |
| 3 | Frame sent to Pi server for analysis | HTTP POST (base64 JSON) |
| 4 | Pi calls Claude Vision API | HTTPS (Anthropic API) |
| 5 | Result returned and displayed live | HTTP JSON response |

**Why this protocol stack:** MJPEG over HTTP is the simplest possible streaming protocol — it's just a continuous multipart HTTP response that any `<img>` tag can consume natively. The analysis path uses plain JSON over HTTP POST, which keeps the Pi server stateless between scans. SSE would add push capability but isn't needed here since the browser controls the scan cadence.

## File structure

```
ee250-visual-search/
├── pi/
│   ├── stream_server.py   # Flask server — stream + analysis + serve dashboard
│   └── requirements.txt
├── dashboard/
│   └── index.html         # Single-page live dashboard
└── README.md
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Camera not found` at startup | Set `CAMERA_INDEX = 1` (or 2) in `stream_server.py` |
| Stream is choppy / laggy | Lower `JPEG_QUALITY` to `50` or reduce resolution to 320×240 in `open_camera()` |
| `/dev/video0` permission denied | `sudo usermod -a -G video $USER` then reboot |
| Dashboard shows "Camera offline" | Check that `stream_server.py` is running; refresh page |
| Claude returns non-JSON | Rare — the server strips markdown fences and retries JSON parse; check Pi terminal for error detail |

## LLM acknowledgment

Claude Code was used to scaffold this project per EE250 guidelines. All code reviewed and understood by [author].

---

## Checklist before running

```
BEFORE YOU RUN:
[ ] HiWonder camera plugged into Pi USB
[ ] Verify: ls /dev/video* shows /dev/video0
[ ] API key is set in pi/stream_server.py (already configured)

TO RUN:
[ ] python3 pi/stream_server.py
[ ] Open browser to the URL printed in terminal
```
