"""Durable recording with explicit provenance; no user-supplied filesystem paths."""
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sqlite3
import uuid


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "recordings.sqlite3"
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, started TEXT NOT NULL, mode TEXT NOT NULL,
                    sensors TEXT NOT NULL, ended TEXT);
                CREATE TABLE IF NOT EXISTS frames (
                    session TEXT NOT NULL REFERENCES sessions(id), seq INTEGER NOT NULL,
                    timestamp TEXT NOT NULL, readings TEXT NOT NULL,
                    PRIMARY KEY(session, seq));
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        try:
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    def start(self, mode, sensors):
        session = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, NULL)",
                       (session, utcnow(), mode, json.dumps(sensors)))
        return session

    def append(self, session, timestamp, readings):
        with self.connect() as db:
            db.execute("INSERT INTO frames SELECT ?, COALESCE(MAX(seq), -1)+1, ?, ? FROM frames WHERE session=?",
                       (session, timestamp, json.dumps(readings, allow_nan=False), session))

    def finish(self, session):
        with self.connect() as db:
            db.execute("UPDATE sessions SET ended=? WHERE id=?", (utcnow(), session))

    def list(self):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute('''SELECT s.id, s.started, s.mode, s.ended,
                COUNT(f.seq) AS samples FROM sessions s LEFT JOIN frames f ON s.id=f.session
                GROUP BY s.id ORDER BY s.started DESC''')]

    def metadata(self, session):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM sessions WHERE id=?", (session,)).fetchone()
        if row is None:
            raise ValueError("Recording not found")
        result = dict(row)
        result["sensors"] = json.loads(result["sensors"])
        return result

    def frames(self, session):
        with self.connect() as db:
            for timestamp, readings in db.execute(
                    "SELECT timestamp, readings FROM frames WHERE session=? ORDER BY seq", (session,)):
                yield {"timestamp": timestamp, "readings": json.loads(readings)}

    def csv_rows(self, session):
        meta = self.metadata(session)
        output = io.StringIO()
        writer = csv.writer(output)
        sensors = meta["sensors"]
        writer.writerow(["timestamp_utc", "source_mode"] + [f'{s["key"]} [{s["unit"]}]' for s in sensors])
        yield output.getvalue()
        for frame in self.frames(session):
            output.seek(0)
            output.truncate(0)
            writer.writerow([frame["timestamp"], meta["mode"]] + [frame["readings"].get(s["key"]) for s in sensors])
            yield output.getvalue()
