"""
EE250 — HiWonder TY-900408-V3.3 MJPEG Stream + Claude Clothing Detection
Single self-contained file — copy only this to the Pi.

Endpoints:
  GET  /            → embedded dashboard
  GET  /video_feed  → live MJPEG stream
  POST /analyze     → { image: "<base64>" } → Claude detection JSON
"""

import base64, cv2, json, os, re, socket, threading, time
import requests as http
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, make_response, request

load_dotenv()

# ── Config ────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]   # loaded from .env
CAMERA_INDEX      = 0       # try 1 or 2 if camera not found at 0
JPEG_QUALITY      = 70      # lower = faster stream, less quality
STREAM_HOST       = "0.0.0.0"
STREAM_PORT       = 5000
# ─────────────────────────────────────────────────────────

CLAUDE_MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """You are a fashion item identifier. Analyze the image and determine if any clothing item is clearly visible.

If YES, respond ONLY with a JSON object:
{
  "detected": true,
  "item_name": "specific item name (e.g. 'Oversized beige linen blazer')",
  "category": "Tops / Bottoms / Outerwear / Footwear / Accessory",
  "color": "primary color",
  "description": "2 sentence style description",
  "style_tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "brand_guesses": ["brand1", "brand2"],
  "price_low": 40,
  "price_high": 200,
  "search_queries": [
    "google shopping query 1",
    "google shopping query 2",
    "google shopping query 3"
  ]
}

If NO clothing is clearly visible, respond ONLY with:
{ "detected": false }

Respond with raw JSON only. No markdown, no explanation."""

CLAUDE_HEADERS = {
    "x-api-key":         ANTHROPIC_API_KEY,
    "anthropic-version": "2023-06-01",
    "content-type":      "application/json",
}

app = Flask(__name__)

# ── Camera init ───────────────────────────────────────────
def open_camera():
    indices = [CAMERA_INDEX] + [i for i in range(3) if i != CAMERA_INDEX]
    for idx in indices:
        cap = cv2.VideoCapture(idx)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            print("Camera opened at index {}".format(idx))
            return cap
        cap.release()
    print("ERROR: No camera found at indices 0, 1, or 2.")
    print("  Check `ls /dev/video*` and set CAMERA_INDEX above.")
    raise SystemExit(1)

cap = open_camera()

# ── Background capture thread ─────────────────────────────
# One thread owns the camera. Any number of browser clients
# read from `_latest_jpeg` simultaneously without lock contention.
_latest_jpeg = None
_jpeg_lock   = threading.Lock()

def _capture_loop():
    global _latest_jpeg
    while True:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.01)
            continue
        cv2.putText(frame, time.strftime("%H:%M:%S"),
                    (8, frame.shape[0] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        with _jpeg_lock:
            _latest_jpeg = buf.tobytes()

threading.Thread(target=_capture_loop, daemon=True).start()


# ── MJPEG stream ──────────────────────────────────────────
def generate_frames():
    while True:
        with _jpeg_lock:
            frame = _latest_jpeg
        if frame is None:
            time.sleep(0.05)
            continue
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
               + frame + b"\r\n")
        time.sleep(0.033)   # cap at ~30 fps per client

@app.route("/video_feed")
def video_feed():
    return Response(generate_frames(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/snapshot")
def snapshot():
    """Return the current frame as base64 JSON — used by the dashboard
    instead of canvas.toDataURL() which returns blank on MJPEG streams."""
    with _jpeg_lock:
        frame = _latest_jpeg
    if frame is None:
        return jsonify({"error": "no frame yet"}), 503
    return jsonify({"image": base64.b64encode(frame).decode()})


# ── Claude analysis ───────────────────────────────────────
@app.route("/analyze", methods=["POST"])
def analyze():
    body = request.get_json(silent=True) or {}
    b64  = body.get("image", "")
    if not b64:
        return jsonify({"detected": False, "error": "no image provided"}), 400
    try:
        resp = http.post(
            "https://api.anthropic.com/v1/messages",
            headers=CLAUDE_HEADERS,
            json={
                "model":      CLAUDE_MODEL,
                "max_tokens": 600,
                "system":     SYSTEM_PROMPT,
                "messages": [{
                    "role": "user",
                    "content": [{"type": "image",
                                 "source": {"type": "base64",
                                            "media_type": "image/jpeg",
                                            "data": b64}}]
                }]
            },
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()["content"][0]["text"]
        m   = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return jsonify({"detected": False, "error": "no JSON in response"}), 502
        return jsonify(json.loads(m.group(0)))
    except json.JSONDecodeError as e:
        return jsonify({"detected": False, "error": "JSON parse error: {}".format(e)}), 502
    except Exception as e:
        return jsonify({"detected": False, "error": str(e)}), 500


# ── Embedded dashboard (index.html UI adapted for Pi stream) ─
# __API_KEY__ is replaced at serve-time with the real key from .env
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ClothingID &mdash; Visual Search</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #0f0f13; --surface: #1a1a24; --border: #2d2d3d;
    --accent: #7c6dff; --accent2: #ff6b9d;
    --text: #e8e8f0; --muted: #7878a0; --green: #4ade80;
    --flash: rgba(255,255,255,0.85);
  }
  body { background:var(--bg); color:var(--text); font-family:'Segoe UI',system-ui,sans-serif; min-height:100vh; display:flex; flex-direction:column; }
  header { padding:16px 32px; border-bottom:1px solid var(--border); display:flex; align-items:center; gap:12px; }
  header h1 { font-size:1.15rem; font-weight:700; }
  header .badge { font-size:.72rem; color:var(--muted); padding:3px 8px; background:var(--surface); border-radius:20px; }
  header .live { margin-left:auto; font-size:.72rem; color:var(--green); display:flex; align-items:center; gap:6px; }
  .dot { width:7px; height:7px; border-radius:50%; background:var(--green); animation:blink 1.2s ease-in-out infinite; }
  @keyframes blink { 0%,100%{opacity:1} 50%{opacity:.2} }
  main { display:grid; grid-template-columns:1fr 1fr; gap:24px; width:100%; max-width:980px; margin:0 auto; padding:24px 20px 40px; flex:1; }
  @media(max-width:680px){ main{ grid-template-columns:1fr; } }
  .cam-panel { display:flex; flex-direction:column; gap:14px; }
  .video-wrap { position:relative; background:#000; border-radius:12px; overflow:hidden; border:1px solid var(--border); aspect-ratio:4/3; }
  #streamImg { width:100%; height:100%; object-fit:cover; display:block; }
  #streamFlash { position:absolute; inset:0; background:var(--flash); opacity:0; pointer-events:none; transition:opacity .05s; }
  #streamOffline { position:absolute; inset:0; display:none; flex-direction:column; align-items:center; justify-content:center; gap:10px; color:var(--muted); font-size:.85rem; }
  .btn-row { display:flex; gap:10px; }
  #scanBtn { flex:1; padding:13px; border:none; border-radius:10px; background:linear-gradient(135deg,var(--accent),var(--accent2)); color:#fff; font-size:.95rem; font-weight:700; cursor:pointer; transition:opacity .2s, transform .1s; }
  #scanBtn:active { transform:scale(.97); }
  #scanBtn:disabled { opacity:.4; cursor:not-allowed; }
  #pauseBtn { padding:13px 20px; border:1px solid var(--border); border-radius:10px; background:var(--surface); color:var(--muted); font-size:.82rem; font-weight:600; cursor:pointer; transition:all .2s; }
  #pauseBtn:hover { border-color:var(--accent); color:var(--accent); }
  #pauseBtn.paused { border-color:#ff6b6b; color:#ff6b6b; }
  .sub-row { display:flex; justify-content:space-between; font-size:.72rem; color:var(--muted); padding:0 2px; }
  .results-panel { display:flex; flex-direction:column; gap:14px; }
  .results-panel h2 { font-size:.82rem; color:var(--muted); text-transform:uppercase; letter-spacing:1px; }
  #resultBox { background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:20px; min-height:200px; display:flex; flex-direction:column; gap:16px; }
  .placeholder { flex:1; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:10px; color:var(--muted); font-size:.85rem; }
  .spinner { width:30px; height:30px; border:3px solid var(--border); border-top-color:var(--accent); border-radius:50%; animation:spin .7s linear infinite; }
  @keyframes spin { to{ transform:rotate(360deg); } }
  .thumb-row { display:flex; gap:14px; align-items:flex-start; }
  #thumb { width:88px; height:88px; object-fit:cover; border-radius:8px; border:1px solid var(--border); flex-shrink:0; }
  .item-info h3 { font-size:1rem; font-weight:700; margin-bottom:4px; }
  .item-price { font-size:.8rem; color:var(--green); font-weight:600; }
  .style-desc { font-size:.8rem; color:var(--muted); line-height:1.65; }
  .tags { display:flex; flex-wrap:wrap; gap:6px; }
  .tag { font-size:.7rem; padding:3px 10px; border-radius:20px; background:rgba(124,109,255,.13); color:var(--accent); border:1px solid rgba(124,109,255,.22); }
  .brands { font-size:.78rem; color:var(--muted); }
  .brands b { color:var(--text); }
  .shop-links { display:flex; flex-direction:column; gap:5px; }
  .shop-links h4 { font-size:.7rem; text-transform:uppercase; letter-spacing:.8px; color:var(--muted); }
  .shop-link { display:flex; align-items:center; gap:8px; padding:8px 12px; background:rgba(255,255,255,.03); border:1px solid var(--border); border-radius:8px; text-decoration:none; color:var(--text); font-size:.8rem; transition:background .15s,border-color .15s; }
  .shop-link:hover { background:rgba(124,109,255,.1); border-color:var(--accent); }
  .shop-num { width:20px; height:20px; background:var(--accent); border-radius:50%; font-size:.68rem; font-weight:700; display:flex; align-items:center; justify-content:center; flex-shrink:0; }
  .shop-link span { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .err { color:#ff6b6b; font-size:.82rem; background:rgba(255,107,107,.07); border:1px solid rgba(255,107,107,.18); border-radius:8px; padding:12px; }
</style>
</head>
<body>
<header>
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2">
    <circle cx="12" cy="12" r="3"/>
    <path d="M20.188 10.934c.2.617.312 1.228.312 1.066s-.112.45-.312 1.066c-.588 1.8-1.9 3.4-3.688 4.5-1.788 1.1-3.912 1.5-6 1.5s-4.212-.4-6-1.5c-1.788-1.1-3.1-2.7-3.688-4.5C.312 12.45.2 11.838.2 12s.112-.45.312-1.066C1.1 9.134 2.412 7.534 4.2 6.434 5.988 5.334 8.112 4.934 10.2 4.934s4.212.4 6 1.5c1.788 1.1 3.1 2.7 3.688 4.5h.3Z"/>
  </svg>
  <h1>ClothingID</h1>
  <span class="badge">EE250 &mdash; Pi Camera</span>
  <div class="live"><div class="dot"></div><span id="liveLabel">connecting...</span></div>
</header>

<main>
  <div class="cam-panel">
    <div class="video-wrap">
      <img id="streamImg" src="/video_feed" alt="Pi camera stream">
      <div id="streamFlash"></div>
      <div id="streamOffline">
        <svg width="40" height="40" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24" opacity=".3">
          <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/>
          <circle cx="12" cy="13" r="4"/>
        </svg>
        Camera offline
      </div>
    </div>
    <div class="btn-row">
      <button id="pauseBtn">&#9208; Auto</button>
      <button id="scanBtn">Scan Item</button>
    </div>
    <div class="sub-row">
      <span id="lastScanTxt">&nbsp;</span>
      <span id="scanStatus">&nbsp;</span>
    </div>
  </div>

  <div class="results-panel">
    <h2>Analysis</h2>
    <div id="resultBox">
      <div class="placeholder" id="placeholder">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity=".25">
          <rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18M3 9h6M3 15h6"/>
        </svg>
        Point camera at clothing and tap Scan
      </div>
    </div>
  </div>
</main>

<script>
var API_KEY = '__API_KEY__';
var CLAUDE_MODEL = 'claude-haiku-4-5-20251001';
var PROMPT = 'Analyze the clothing item(s) visible in this image. Return ONLY a JSON object with exactly these fields: {"item_name":"specific name","style_description":"2-3 sentences on style, cut, color, occasion","tags":["t1","t2","t3","t4","t5"],"brand_guesses":["b1","b2"],"price_range":"$XX-$XX USD estimated retail","search_queries":["q1","q2","q3"]}';

var paused = false, scanInterval = null, lastScanTime = null;
var streamImg = document.getElementById('streamImg');

streamImg.addEventListener('load', function(){
  document.getElementById('streamOffline').style.display = 'none';
  document.getElementById('liveLabel').textContent = 'LIVE';
  document.getElementById('liveLabel').style.color = 'var(--green)';
  document.getElementById('scanBtn').disabled = false;
});
streamImg.addEventListener('error', function(){
  document.getElementById('streamOffline').style.display = 'flex';
  document.getElementById('liveLabel').textContent = 'offline';
  document.getElementById('liveLabel').style.color = '#ff6b6b';
});

document.getElementById('scanBtn').disabled = true;

async function doScan() {
  if (paused) return;
  setScanStatus('scanning...');
  var flash = document.getElementById('streamFlash');
  flash.style.opacity = '1';
  setTimeout(function(){ flash.style.opacity = '0'; }, 120);

  try {
    var snap = await fetch('/snapshot').then(function(r){ return r.json(); });
    if (snap.error) throw new Error(snap.error);

    var res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'x-api-key': API_KEY,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json',
        'anthropic-dangerous-direct-browser-access': 'true'
      },
      body: JSON.stringify({
        model: CLAUDE_MODEL,
        max_tokens: 700,
        messages: [{
          role: 'user',
          content: [
            { type: 'image', source: { type: 'base64', media_type: 'image/jpeg', data: snap.image } },
            { type: 'text', text: PROMPT }
          ]
        }]
      })
    });
    if (!res.ok) {
      var e = await res.json().catch(function(){ return {}; });
      throw new Error(e.error && e.error.message ? e.error.message : 'API error ' + res.status);
    }
    var data = await res.json();
    var text = data.content[0].text.trim();
    var jsonStr = text.startsWith('{') ? text : (text.match(/\\{[\\s\\S]*\\}/) || [''])[0];
    renderResult(JSON.parse(jsonStr), 'data:image/jpeg;base64,' + snap.image);
    lastScanTime = Date.now();
    setScanStatus('');
  } catch(err) {
    document.getElementById('resultBox').innerHTML = '<div class="err">&#9888; ' + esc(err.message) + '</div>';
    setScanStatus('error');
    setTimeout(function(){ setScanStatus(''); }, 3000);
  }
}

function renderResult(r, thumbSrc) {
  var shopLinks = (r.search_queries || []).map(function(q, i){
    var url = 'https://www.google.com/search?tbm=shop&q=' + encodeURIComponent(q);
    return '<a class="shop-link" href="' + url + '" target="_blank" rel="noopener">'
      + '<span class="shop-num">' + (i+1) + '</span>'
      + '<span>' + esc(q) + '</span>'
      + '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--muted)" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>'
      + '</a>';
  }).join('');
  var tags = (r.tags || []).map(function(t){ return '<span class="tag">' + esc(t) + '</span>'; }).join('');
  var brands = (r.brand_guesses || []).join(', ');
  document.getElementById('resultBox').innerHTML =
    '<div class="thumb-row">'
    + '<img id="thumb" src="' + thumbSrc + '" alt="captured"/>'
    + '<div class="item-info"><h3>' + esc(r.item_name || '') + '</h3>'
    + '<div class="item-price">' + esc(r.price_range || '') + '</div></div>'
    + '</div>'
    + '<div class="style-desc">' + esc(r.style_description || '') + '</div>'
    + '<div class="tags">' + tags + '</div>'
    + (brands ? '<div class="brands"><b>Likely brands:</b> ' + esc(brands) + '</div>' : '')
    + '<div class="shop-links"><h4>Shop on Google</h4>' + shopLinks + '</div>';
}

function setScanStatus(s) {
  document.getElementById('scanStatus').textContent = s;
}

setInterval(function(){
  if (!lastScanTime) return;
  var s = Math.round((Date.now() - lastScanTime) / 1000);
  document.getElementById('lastScanTxt').textContent = 'Last scan: ' + s + 's ago';
}, 1000);

function startLoop() {
  if (scanInterval) clearInterval(scanInterval);
  scanInterval = setInterval(doScan, 4000);
}
startLoop();

document.getElementById('scanBtn').addEventListener('click', function(){
  doScan();
  if (!paused) startLoop();
});

document.getElementById('pauseBtn').addEventListener('click', function(){
  paused = !paused;
  var btn = document.getElementById('pauseBtn');
  if (paused) {
    btn.textContent = '&#9654; Paused';
    btn.classList.add('paused');
    clearInterval(scanInterval);
  } else {
    btn.textContent = '&#9208; Auto';
    btn.classList.remove('paused');
    startLoop();
  }
});

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
</script>
</body>
</html>"""

@app.route("/")
def dashboard():
    html = DASHBOARD_HTML.replace("__API_KEY__", ANTHROPIC_API_KEY)
    resp = make_response(html)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


# ── Entry point ───────────────────────────────────────────
def _get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"

if __name__ == "__main__":
    local_ip = _get_local_ip()
    print("-" * 50)
    print("  Dashboard:  http://{}:{}".format(local_ip, STREAM_PORT))
    print("  Stream:     http://{}:{}/video_feed".format(local_ip, STREAM_PORT))
    print("-" * 50)
    app.run(host=STREAM_HOST, port=STREAM_PORT, debug=False, threaded=True)
