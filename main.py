import json
import queue
import threading
from flask import Flask, request, jsonify, render_template, Response, stream_with_context
from agent import parse_and_run, get_jobs
import browser as browser_module

app = Flask(__name__)

# Per-request event queue for SSE
_event_queue: queue.Queue = None


def _emit_event(event: dict):
    if _event_queue:
        _event_queue.put(event)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_message = data.get("message", "").strip()
    skip_search = data.get("skip_search", False)
    if not user_message:
        return jsonify({"reply": "Say something!"})
    # if the UI is already streaming a search via SSE, don't re-run the scrape
    if skip_search:
        return jsonify({"reply": "__streaming__"})
    reply = parse_and_run(user_message)
    return jsonify({"reply": reply})


@app.route("/search-stream")
def search_stream():
    """SSE endpoint — streams live scraping events to the browser pane."""
    query = request.args.get("q", "").strip()
    if not query:
        return Response("data: {\"type\":\"error\",\"msg\":\"No query\"}\n\n",
                        mimetype="text/event-stream")

    q: queue.Queue = queue.Queue()

    def emit(event: dict):
        q.put(event)

    def run_scrape():
        browser_module.set_emit(emit)
        import json as _json
        from agent import _do_search
        try:
            _do_search(query)
        except Exception as e:
            emit({"type": "error", "msg": str(e)})
        finally:
            emit({"type": "done"})
            browser_module.set_emit(None)

    t = threading.Thread(target=run_scrape, daemon=True)
    t.start()

    def generate():
        while True:
            try:
                event = q.get(timeout=60)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") == "done":
                    break
            except queue.Empty:
                yield "data: {\"type\":\"ping\"}\n\n"

    return Response(stream_with_context(generate()),
                    mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    app.run(debug=False, port=5000, threaded=True)
