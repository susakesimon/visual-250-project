# ClothingID — EE250 Vision System (SSE edition)

**Team Members:** Simon Solomon, Stephanie Muoka

Three-node IoT pipeline: Pi camera → Flask server → browser/terminal display.
No MQTT broker needed. No ESP32 required.

## Architecture

```
[Pi camera node]
   pi_camera.py
       │ polls /trigger-check (HTTP GET, every 2s)
       │ uploads image (HTTP POST /analyze)
       ▼
[Flask server — 10.23.198.21:5000]
   server.py
       │ calls Claude vision API
       │ calls SerpApi (Google Shopping)
       │ broadcasts result via Server-Sent Events
       ├─► GET /stream  ──────────────────────────► [Node 3B — browser]
       │                                                dashboard.html
       └─► GET /latest  ──────────────────────────► [Node 3A — terminal]
                                                        display.py
```

**Why SSE over MQTT?**
SSE is HTTP-native (no broker process, no extra library), inherently one-directional
(server→client — exactly what a display node needs), and auto-reconnects on drop.
Simpler dependency graph, easier to explain in a write-up.

---

## Quick-start

### 1. Edit `config.py` — two lines only

```python
ANTHROPIC_API_KEY = "sk-ant-..."        # ← paste your key
# SERVER_IP is already set to 10.23.198.21
```

### 2. Install server deps (laptop)

```bash
pip install flask anthropic "serpapi[google_search_results]"
```

### 3. Install Pi deps

```bash
pip install requests pillow picamera2
# OLED optional: pip install luma.oled
# OpenCV fallback: pip install opencv-python-headless
```

### 4. Run

```bash
# Laptop — terminal 1
python server.py
# → http://10.23.198.21:5000  (dashboard)

# Pi — terminal
python pi_camera.py

# Node 3A — any laptop on same WiFi
python display.py

# Node 3B — open in any browser
open http://10.23.198.21:5000
```

### 5. Trigger a scan

- **Dashboard** → click the **▶ Capture** button (sets server flag → Pi picks it up)
- **GPIO button** → set `GPIO_BUTTON_PIN` in `pi_camera.py` to your BCM pin
- **curl** → `curl -X POST http://10.23.198.21:5000/trigger`

### 6. Curl test (no Pi needed)

```bash
B64=$(base64 -i test.jpg)
curl -X POST http://10.23.198.21:5000/analyze \
     -H "Content-Type: application/json" \
     -d "{\"image\":\"$B64\"}" | python -m json.tool
```

---

## File map

```
VisualProject/
├── index.html       standalone browser demo (webcam → Claude direct)
├── config.py        all configuration — edit once
├── server.py        Flask + SSE + Claude + SerpApi + trend scoring
├── trend_scorer.py  K-Means clustering — tracks item popularity across scans
├── pi_camera.py     Node 1 — Pi capture → HTTP POST
├── display.py       Node 3A — terminal OLED mimic
├── dashboard.html   Node 3B — browser dashboard (served by Flask at /)
└── README.md
```

## External libraries

| Library | Where used | Install |
|---------|-----------|---------|
| [Flask](https://flask.palletsprojects.com/) | HTTP server, SSE stream, static file serving | `pip install flask` |
| [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python) | Claude vision API (image → JSON analysis) | `pip install anthropic` |
| [SerpApi](https://serpapi.com/) | Google Shopping search results | `pip install "serpapi[google_search_results]"` |
| [Requests](https://docs.python-requests.org/) | Pi node HTTP client (POST image, GET trigger) | `pip install requests` |
| [Pillow](https://python-pillow.org/) | JPEG capture and resizing on the Pi | `pip install pillow` |
| [Picamera2](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf) | Raspberry Pi camera interface | `pip install picamera2` |
| [scikit-learn](https://scikit-learn.org/) | K-Means clustering for trend scoring | `pip install scikit-learn` |
| [NumPy](https://numpy.org/) | Feature vector math inside trend scorer | `pip install numpy` |
| luma.oled *(optional)* | Physical SSD1306 OLED display on Pi | `pip install luma.oled` |
| opencv-python-headless *(optional)* | Fallback camera capture if Picamera2 unavailable | `pip install opencv-python-headless` |

---

## Protocol reference

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Serve dashboard.html |
| `/analyze` | POST | Upload image (base64 JSON) → get analysis JSON |
| `/stream` | GET | SSE stream — subscribe for live results |
| `/latest` | GET | Most recent result as JSON (polling fallback) |
| `/trigger` | POST | Signal Pi to capture (dashboard button → Pi poll) |
| `/trigger-check` | GET | Pi calls this; returns `{trigger: true/false}` |
| `/reset` | POST | Clear trend session data (resets K-Means history) |
| `/health` | GET | Server status + connected SSE client count |
