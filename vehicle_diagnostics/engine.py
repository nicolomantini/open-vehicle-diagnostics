"""One worker owns serial I/O; HTTP readers never perform vehicle queries."""
import copy
from datetime import datetime
import queue
import threading
import time

from .backends import Simulator, Vehicle, catalog
from .storage import utcnow


class Engine:
    def __init__(self, store, vehicle_factory=Vehicle):
        self.store = store
        self.vehicle_factory = vehicle_factory
        self.backend = None
        self.recording = None
        self.replay = None
        self.actions = queue.Queue(maxsize=20)
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.state = dict(mode="disconnected", status="Disconnected", sensors=[], readings={},
                          timestamp=None, recording=None, faults=None, error=None, supported_commands=[])

    def update(self, **kwargs):
        with self.lock:
            self.state.update(kwargs)

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def submit(self, action, **args):
        self.actions.put_nowait((action, args))

    def disconnect(self):
        failures = []
        if self.recording:
            try:
                self.store.finish(self.recording)
            except Exception as exc:
                failures.append(str(exc))
            self.recording = None
        if self.backend:
            try:
                self.backend.close()
            except Exception as exc:
                failures.append(str(exc))
            self.backend = None
        if self.replay:
            self.replay["frames"].close()
        self.replay = None
        self.update(mode="disconnected", status="Disconnected", recording=None, sensors=[],
                    readings={}, timestamp=None, faults=None, supported_commands=[], replay_source=None,
                    protocol=None)
        if failures:
            self.update(error="Cleanup error: " + "; ".join(failures))

    def act(self, action, args):
        self.update(error=None)
        if action == "disconnect":
            self.disconnect()
        elif action == "connect":
            self.disconnect()
            self.update(status="Connecting…")
            try:
                self.backend = Simulator() if args["mode"] == "simulator" else self.vehicle_factory(
                    port=args.get("port"), baudrate=args.get("baudrate"))
            except Exception:
                self.update(status="Connection failed")
                raise
            self.update(mode=self.backend.mode, status="Connected", sensors=catalog(self.backend.sensors),
                        supported_commands=getattr(self.backend, "supported_commands", []),
                        protocol=getattr(self.backend, "protocol", "Synthetic data"), stream_id=utcnow())
        elif action == "faults":
            if not self.backend:
                raise ValueError("Connect to a vehicle or simulator before reading faults")
            self.update(faults={"source_mode": self.backend.mode, "timestamp": utcnow(),
                                "results": self.backend.faults()})
        elif action == "record_start":
            if not self.backend or self.recording:
                raise ValueError("Recording requires a live connection and no active recording")
            self.recording = self.store.start(self.backend.mode, catalog(self.backend.sensors))
            self.update(recording=self.recording)
        elif action == "record_stop":
            if self.recording:
                self.store.finish(self.recording)
                self.recording = None
                self.update(recording=None)
        elif action == "replay":
            meta = self.store.metadata(args["id"])
            frames = self.store.frames(args["id"])
            first = next(frames, None)
            if first is None:
                frames.close()
                raise ValueError("This recording has no samples")
            self.disconnect()
            self.replay = dict(frames=frames, next=first, start=time.monotonic(),
                               original=datetime.fromisoformat(first["timestamp"]).timestamp())
            self.update(mode="replay", status="Replaying", sensors=meta["sensors"], replay_source=meta["mode"], stream_id=utcnow())
        else:
            raise ValueError("Unknown action")

    def tick(self):
        try:
            action, args = self.actions.get_nowait()
        except queue.Empty:
            pass
        else:
            try:
                self.act(action, args)
            except Exception as exc:
                self.update(error=str(exc))
        try:
            if self.backend:
                readings = self.backend.read()
                timestamp = utcnow()
                if self.recording:
                    self.store.append(self.recording, timestamp, readings)
                self.update(readings=readings, timestamp=timestamp)
            elif self.replay:
                replay = self.replay
                frame = replay["next"]
                due = datetime.fromisoformat(frame["timestamp"]).timestamp() - replay["original"]
                if time.monotonic() - replay["start"] >= due:
                    self.update(**frame)
                    replay["next"] = next(replay["frames"], None)
                    if replay["next"] is None:
                        replay["frames"].close()
                        self.replay = None
                        self.update(status="Replay complete")
        except Exception as exc:
            self.disconnect()
            self.update(status="Connection / recording error", error=str(exc))

    def start(self):
        def run():
            try:
                while not self.stop_event.is_set():
                    self.tick()
                    self.stop_event.wait(0.5)
            finally:
                self.disconnect()
        self.thread = threading.Thread(target=run, name="diagnostics", daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=40)
