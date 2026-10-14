import argparse
import json
from pathlib import Path
import queue
import secrets

from flask import Flask, Response, abort, jsonify, request

from .backends import ports
from .engine import Engine
from .storage import Store


def create_app(data_dir=None, start_worker=False, trusted_hosts=None):
    app = Flask(__name__, static_folder="static")
    app.config.update(MAX_CONTENT_LENGTH=4096, TRUSTED_HOSTS=trusted_hosts or ["localhost", "127.0.0.1", "[::1]"])
    token = secrets.token_urlsafe(32)
    store = Store(data_dir or Path(__file__).resolve().parent.parent / "data")
    engine = Engine(store)
    app.extensions["diagnostics"] = engine
    app.extensions["api_token"] = token

    @app.before_request
    def protect():
        if request.method == "POST":
            if not secrets.compare_digest(request.headers.get("X-Diagnostics-Token", ""), token):
                abort(403)
            if not request.is_json:
                abort(415)

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'"
        return response

    @app.get("/")
    def index():
        html = (Path(app.static_folder) / "index.html").read_text()
        return Response(html.replace("__TOKEN__", token), mimetype="text/html")

    @app.get("/api/status")
    def status():
        return jsonify(engine.snapshot())

    @app.get("/api/ports")
    def adapter_ports():
        return jsonify(ports())

    @app.post("/api/action")
    def action():
        data = request.get_json()
        if not isinstance(data, dict):
            abort(400)
        name = data.get("action")
        if not isinstance(name, str) or name not in {"connect", "disconnect", "faults", "record_start", "record_stop", "replay"}:
            return jsonify(error="Unknown action"), 400
        args = {}
        if name == "connect":
            if data.get("mode") not in {"vehicle", "simulator"}:
                return jsonify(error="Choose vehicle or simulator"), 400
            port = data.get("port") or None
            if port and (not isinstance(port, str) or port not in {p["device"] for p in ports()}):
                return jsonify(error="Serial port is no longer present; refresh adapters"), 400
            baud = data.get("baudrate") or None
            if baud is not None and (type(baud) is not int or baud not in {9600, 38400, 115200, 230400, 500000}):
                return jsonify(error="Unsupported baud rate"), 400
            args = dict(mode=data["mode"], port=port, baudrate=baud)
        elif name == "replay":
            if not isinstance(data.get("id"), str):
                abort(400)
            try:
                store.metadata(data["id"])
            except ValueError:
                abort(404)
            args = {"id": data["id"]}
        try:
            engine.submit(name, **args)
        except queue.Full:
            return jsonify(error="Busy; wait before retrying"), 429
        return jsonify(queued=True), 202

    @app.get("/api/recordings")
    def recordings():
        return jsonify(store.list())

    @app.get("/api/recordings/<session>/csv")
    def export(session):
        try:
            store.metadata(session)
        except ValueError:
            abort(404)
        return Response(store.csv_rows(session), mimetype="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="recording-{session}.csv"'})

    @app.get("/api/faults/report")
    def fault_report():
        faults = engine.snapshot()["faults"]
        if faults is None:
            abort(404)
        return Response(json.dumps(faults, indent=2), mimetype="application/json",
                        headers={"Content-Disposition": 'attachment; filename="fault-report.json"'})

    if start_worker:
        engine.start()
    return app


def main():
    parser = argparse.ArgumentParser(description="Local, read-only vehicle diagnostics")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--trusted-host", action="append", default=[])
    args = parser.parse_args()
    hosts = ["localhost", "127.0.0.1", "[::1]"] + args.trusted_host
    app = create_app(args.data_dir, start_worker=True, trusted_hosts=hosts)
    try:
        app.run(host=args.host, port=args.port, threaded=True, use_reloader=False)
    finally:
        app.extensions["diagnostics"].close()


if __name__ == "__main__":
    main()
