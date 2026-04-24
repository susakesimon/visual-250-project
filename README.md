# ClothingID — EE250 Vision System

**Team Members:** Simon Solomon, Stephanie Muoka

IoT clothing identification system: Pi camera streams live video → browser dashboard runs Claude AI analysis → shopping links open on any device on the same network.

---

## How it works

```
[Raspberry Pi]
   ee250-visual-search/pi/stream_server.py
       │ opens USB/CSI camera
       │ serves live MJPEG stream  → GET /video_feed
       │ serves embedded dashboard → GET /
       │ exposes snapshot endpoint → GET /snapshot
       ▼
[Same WiFi network]
       │
       ▼
[Laptop / any device — browser only, no install needed]
   Open http://<Pi-IP>:5000
       • watches live camera feed
       • clicks "Scan Item" or waits for auto-scan (every 4s)
       • browser calls Claude API directly with the snapshot
       • results + Google Shopping links appear on screen
       • clicking a link opens Google Shopping on the laptop
```

**Why run the server on the Pi?**
Everything is self-contained — one file, one process. The laptop is just a browser; no Python setup required on it. The Pi auto-detects its IP and prints the URL on startup.

---

## Quick-start

### 1. Set up the Pi

Copy the project to the Pi, then create a `.env` file next to `stream_server.py`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

### 2. Install Pi deps

```bash
pip install flask python-dotenv opencv-python requests
```

### 3. Run on the Pi

```bash
cd ee250-visual-search/pi
python stream_server.py
```

The terminal will print:
```
--------------------------------------------------
  Dashboard:  http://10.x.x.x:5000
  Stream:     http://10.x.x.x:5000/video_feed
--------------------------------------------------
```

### 4. Open on the laptop

Make sure the laptop is on the **same WiFi network** as the Pi, then open the printed URL in any browser.

### 5. Scan

- **Auto mode** — dashboard scans automatically every 4 seconds
- **Manual** — click **Scan Item** to trigger immediately
- **Pause** — click the **⏸ Auto** button to stop auto-scanning

Results show the identified item, style description, tags, brand guesses, price range, and Google Shopping links. Clicking any link opens it on your laptop.

---

## File map

```
VisualProject/
├── ee250-visual-search/
│   └── pi/
│       └── stream_server.py   ← main file — run this on the Pi
├── server.py                  extended SSE version with trend scoring (laptop server)
├── trend_scorer.py            K-Means clustering — tracks item popularity across scans
├── dashboard.html             SSE dashboard for the extended server.py setup
├── pi_camera.py               Pi camera node for the extended server.py setup
├── display.py                 terminal display node for the extended server.py setup
├── index.html                 standalone browser demo (webcam → Claude direct)
├── config.py                  configuration for the extended server.py setup
└── README.md
```

---

## External libraries

| Library | Where used | Install |
|---------|-----------|---------|
| [Flask](https://flask.palletsprojects.com/) | HTTP server, MJPEG stream, dashboard serving | `pip install flask` |
| [OpenCV (cv2)](https://opencv.org/) | Camera capture and JPEG encoding on the Pi | `pip install opencv-python` |
| [python-dotenv](https://pypi.org/project/python-dotenv/) | Load `ANTHROPIC_API_KEY` from `.env` file | `pip install python-dotenv` |
| [Requests](https://docs.python-requests.org/) | HTTP client calls from Pi to Claude API | `pip install requests` |
| [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python) | Claude vision API in extended server.py mode | `pip install anthropic` |
| [SerpApi](https://serpapi.com/) | Google Shopping results in extended server.py mode | `pip install "serpapi[google_search_results]"` |
| [scikit-learn](https://scikit-learn.org/) | K-Means clustering for trend scoring | `pip install scikit-learn` |
| [NumPy](https://numpy.org/) | Feature vector math inside trend scorer | `pip install numpy` |
| [Pillow](https://python-pillow.org/) | JPEG handling in extended Pi camera node | `pip install pillow` |
| [Picamera2](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf) | Native Pi camera interface (extended mode) | `pip install picamera2` |

---

## Protocol reference

### `stream_server.py` endpoints (Pi)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Serve embedded dashboard |
| `/video_feed` | GET | Live MJPEG camera stream |
| `/snapshot` | GET | Current frame as base64 JSON (used by dashboard to send to Claude) |
| `/analyze` | POST | Server-side Claude analysis (unused in browser-direct mode) |

### `server.py` endpoints (extended mode, runs on laptop)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Serve dashboard.html |
| `/analyze` | POST | Upload image → Claude + SerpApi → analysis JSON |
| `/stream` | GET | SSE stream — subscribe for live results |
| `/latest` | GET | Most recent result as JSON (polling fallback) |
| `/trigger` | POST | Signal Pi to capture (dashboard button → Pi poll) |
| `/trigger-check` | GET | Pi calls this; returns `{trigger: true/false}` |
| `/reset` | POST | Clear trend session data (resets K-Means history) |
| `/health` | GET | Server status + connected SSE client count |
