"""
ClothingID — Flask server node (SSE edition)
Runs on your laptop at SERVER_IP:5000.

Endpoints:
  GET  /              → serve dashboard.html (Node 3B)
  POST /analyze       → receive JPEG (base64 JSON), run Claude+SerpApi,
                        broadcast result to all SSE clients, return JSON
  GET  /stream        → Server-Sent Events stream (dashboard subscribes here)
  GET  /latest        → last result as JSON  (display.py polls here)
  POST /trigger       → set a one-shot trigger flag  (dashboard "Capture" btn)
  GET  /trigger-check → Pi polls this; returns {trigger: true/false}

Install deps:
  pip install flask anthropic "serpapi[google_search_results]"
"""

import base64, json, os, queue, re, threading, time, logging
from typing import Optional
import anthropic
from flask import Flask, Response, jsonify, request, send_from_directory
from serpapi import GoogleSearch
from trend_scorer import update_trend_score, reset as reset_trend_data
from config import (
    ANTHROPIC_API_KEY, SERPAPI_KEY, SERVER_IP,
    FLASK_HOST, FLASK_PORT,
    CLAUDE_MODEL, MAX_TOKENS,
    SERPAPI_ENGINE, SERPAPI_RESULTS,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [server] %(message)s")
log = logging.getLogger(__name__)

app       = Flask(__name__)
claude    = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── SSE state ─────────────────────────────────────────────
_clients: list[queue.Queue] = []
_clients_lock  = threading.Lock()
_latest_result: Optional[dict] = None
_trigger_flag  = threading.Event()     # set by dashboard, cleared by Pi

VISION_PROMPT = """Analyze the clothing item(s) in this image.
Return ONLY a JSON object — no markdown, no extra text — with exactly these fields:
{
  "item_name": "specific item name",
  "style_description": "2-3 sentences on style, cut, color, occasion",
  "tags": ["tag1","tag2","tag3","tag4","tag5"],
  "brand_guesses": ["most likely brand","second guess"],
  "price_range": "$XX-$XX USD estimated retail",
  "search_queries": ["query1","query2","query3"]
}"""


def _broadcast(payload: dict):
    """Push a result to every connected SSE client."""
    global _latest_result
    _latest_result = payload
    encoded = json.dumps(payload)
    with _clients_lock:
        stale = []
        for q in _clients:
            try:
                q.put_nowait(encoded)
            except queue.Full:
                stale.append(q)
        for q in stale:
            _clients.remove(q)


def _sse_generator():
    """Generator that yields SSE frames; one per connected client."""
    q: queue.Queue = queue.Queue(maxsize=10)
    with _clients_lock:
        _clients.append(q)
    # send current state immediately so late joiners see the last result
    if _latest_result:
        yield f"data: {json.dumps(_latest_result)}\n\n"
    try:
        while True:
            try:
                data = q.get(timeout=20)
                yield f"data: {data}\n\n"
            except queue.Empty:
                yield ": heartbeat\n\n"   # keep connection alive
    except GeneratorExit:
        pass
    finally:
        with _clients_lock:
            if q in _clients:
                _clients.remove(q)


# ── Analysis pipeline ─────────────────────────────────────
def analyse_image(b64: str, media_type: str = "image/jpeg") -> dict:
    log.info("Calling Claude vision API…")
    msg = claude.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64",
                                              "media_type": media_type,
                                              "data": b64}},
                {"type": "text", "text": VISION_PROMPT},
            ],
        }],
    )
    raw = msg.content[0].text.strip()
    if not raw.startswith("{"):
        m = re.search(r"\{[\s\S]*\}", raw)
        raw = m.group(0) if m else raw
    result = json.loads(raw)
    log.info("Claude: %s", result.get("item_name"))

    shopping = []
    for query in result.get("search_queries", [])[:SERPAPI_RESULTS]:
        try:
            sr = GoogleSearch({"engine": SERPAPI_ENGINE, "q": query,
                               "api_key": SERPAPI_KEY, "num": 3}).get_dict()
            for h in sr.get("shopping_results", [])[:3]:
                shopping.append({
                    "title":     h.get("title", ""),
                    "price":     h.get("price", ""),
                    "source":    h.get("source", ""),
                    "link":      h.get("link", ""),
                    "thumbnail": h.get("thumbnail", ""),
                    "query":     query,
                })
            log.info("SerpApi '%s' → %d hits", query, len(sr.get("shopping_results", [])))
        except Exception as e:
            log.warning("SerpApi error for '%s': %s", query, e)

    result["shopping_results"] = shopping

    trend = update_trend_score(
        item_type=result.get("item_name", "unknown"),
        confidence="high",
        products=shopping,
    )
    result["trend_label"] = trend["trend_label"]
    result["trend_score"] = trend["trend_score"]
    result["item_count"]  = trend["item_count"]

    result["timestamp"] = time.strftime("%H:%M:%S")
    return result


# ── Flask routes ──────────────────────────────────────────
@app.route("/")
def serve_dashboard():
    base = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(base, "dashboard.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    if request.is_json:
        body = request.get_json()
        b64  = body.get("image", "")
        mt   = body.get("media_type", "image/jpeg")
    elif "image" in request.files:
        f    = request.files["image"]
        b64  = base64.b64encode(f.read()).decode()
        mt   = f.mimetype or "image/jpeg"
    else:
        return jsonify({"error": "send JSON {image:<base64>} or multipart 'image' file"}), 400

    if not b64:
        return jsonify({"error": "empty image"}), 400

    try:
        result = analyse_image(b64, mt)
        _broadcast(result)
        return jsonify(result)
    except json.JSONDecodeError as e:
        return jsonify({"error": "model returned invalid JSON", "detail": str(e)}), 502
    except Exception as e:
        log.exception("Analysis failed")
        return jsonify({"error": str(e)}), 500


@app.route("/stream")
def stream():
    return Response(
        _sse_generator(),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/latest")
def latest():
    if _latest_result:
        return jsonify(_latest_result)
    return jsonify({"status": "no results yet"}), 204


@app.route("/trigger", methods=["POST"])
def trigger():
    _trigger_flag.set()
    log.info("Trigger flag set by dashboard")
    return jsonify({"ok": True})


@app.route("/trigger-check")
def trigger_check():
    fired = _trigger_flag.is_set()
    if fired:
        _trigger_flag.clear()
    return jsonify({"trigger": fired})


@app.route("/reset", methods=["POST"])
def reset_trends():
    reset_trend_data()
    log.info("Trend data reset")
    return jsonify({"ok": True})


@app.route("/health")
def health():
    return jsonify({"status": "ok", "server_ip": SERVER_IP,
                    "sse_clients": len(_clients)})


if __name__ == "__main__":
    log.info("Dashboard → http://%s:%d", SERVER_IP, FLASK_PORT)
    log.info("SSE stream → http://%s:%d/stream", SERVER_IP, FLASK_PORT)
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False, threaded=True)
