import csv
import io
from types import SimpleNamespace

import obd
import pytest

from vehicle_diagnostics.backends import SENSORS, Simulator, Vehicle
from vehicle_diagnostics.engine import Engine
from vehicle_diagnostics.storage import Store
from vehicle_diagnostics.web import create_app


class FakeConnection:
    def __init__(self, **kwargs):
        self.supported_commands = {obd.commands.RPM, obd.commands.COOLANT_TEMP}
        self.connected = True
        self.closed = False
        self.null = False
        self.queries = []

    def supports(self, command):
        return command in self.supported_commands

    def is_connected(self):
        return self.connected

    def status(self):
        return "ELM Connected"

    def protocol_name(self):
        return "Test protocol"

    def close(self):
        self.closed = True

    def query(self, command, force=False):
        self.queries.append(command.name)
        value = obd.Unit.Quantity(2000, "rpm") if command == obd.commands.RPM else obd.Unit.Quantity(85, "degC")
        if command in {obd.commands.GET_DTC, obd.commands.GET_CURRENT_DTC}:
            value = []
        return SimpleNamespace(is_null=lambda: self.null, value=value)


def test_vehicle_discovery_units_and_only_supported_queries():
    fake = FakeConnection()
    vehicle = Vehicle(factory=lambda **kw: fake)
    assert [s.key for s in vehicle.sensors] == ["rpm", "coolant"]
    assert vehicle.read() == {"rpm": 2000, "coolant": 85}
    assert fake.queries == ["RPM", "COOLANT_TEMP"]
    vehicle.close()
    assert fake.closed


def test_failed_connection_is_closed():
    fake = FakeConnection()
    fake.connected = False
    with pytest.raises(ConnectionError):
        Vehicle(factory=lambda **kw: fake)
    assert fake.closed


def test_no_response_is_not_zero_or_no_faults():
    fake = FakeConnection()
    vehicle = Vehicle(factory=lambda **kw: fake)
    fake.null = True
    assert vehicle.read() == {"rpm": None, "coolant": None}
    assert vehicle.faults()["stored"]["status"] == "no_response"
    vehicle.read()
    with pytest.raises(ConnectionError, match="three polling"):
        vehicle.read()


def test_empty_fault_list_is_valid_response():
    vehicle = Vehicle(factory=FakeConnection)
    assert vehicle.faults()["stored"] == {"status": "ok", "codes": []}


def test_record_replay_and_csv_provenance(tmp_path):
    store = Store(tmp_path)
    engine = Engine(store)
    engine.submit("connect", mode="simulator")
    engine.tick()
    engine.submit("record_start")
    engine.tick()
    session = engine.recording
    engine.submit("record_stop")
    engine.tick()
    rows = list(csv.reader(io.StringIO(''.join(store.csv_rows(session)))))
    assert rows[0][:2] == ["timestamp_utc", "source_mode"]
    assert rows[1][1] == "simulator"
    original = next(store.frames(session))
    engine.submit("replay", id=session)
    engine.tick()
    state = engine.snapshot()
    assert engine.backend is None
    assert state["mode"] == "replay" and state["replay_source"] == "simulator"
    assert state["readings"] == original["readings"]
    assert state["timestamp"] == original["timestamp"]
    assert state["status"] == "Replay complete"
    assert store.list()[0]["ended"]


def test_replay_respects_original_timing(tmp_path, monkeypatch):
    store = Store(tmp_path)
    session = store.start("vehicle", [])
    store.append(session, "2026-01-01T00:00:00+00:00", {"rpm": 1})
    store.append(session, "2026-01-01T00:00:05+00:00", {"rpm": 2})
    clock = [100.0]
    monkeypatch.setattr("vehicle_diagnostics.engine.time.monotonic", lambda: clock[0])
    engine = Engine(store)
    engine.submit("replay", id=session)
    engine.tick()
    assert engine.snapshot()["readings"]["rpm"] == 1
    clock[0] += 4
    engine.tick()
    assert engine.snapshot()["readings"]["rpm"] == 1
    clock[0] += 1
    engine.tick()
    assert engine.snapshot()["readings"]["rpm"] == 2


def test_disconnect_finishes_recording_and_clears_stale_data(tmp_path):
    engine = Engine(Store(tmp_path))
    engine.act("connect", {"mode": "simulator"})
    engine.act("record_start", {})
    engine.tick()
    engine.act("faults", {})
    engine.act("disconnect", {})
    assert engine.snapshot()["readings"] == {}
    assert engine.snapshot()["faults"] is None
    assert engine.store.list()[0]["ended"]


def test_io_failure_does_not_kill_worker(tmp_path):
    engine = Engine(Store(tmp_path))
    engine.act("connect", {"mode": "simulator"})
    engine.backend.read = lambda: (_ for _ in ()).throw(OSError("USB unplugged"))
    engine.tick()
    assert engine.snapshot()["mode"] == "disconnected"
    assert "USB unplugged" in engine.snapshot()["error"]
    engine.submit("connect", mode="simulator")
    engine.tick()
    assert engine.snapshot()["mode"] == "simulator"


def test_null_csv_cell_and_missing_recording(tmp_path):
    store = Store(tmp_path)
    session = store.start("vehicle", [{"key": "rpm", "unit": "rpm"}])
    store.append(session, "2026-01-01T00:00:00+00:00", {"rpm": None})
    assert list(csv.reader(io.StringIO(''.join(store.csv_rows(session)))))[1][-1] == ''
    with pytest.raises(ValueError):
        store.metadata("../../etc/passwd")


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path)


def test_http_security_and_validation(app):
    client = app.test_client()
    assert client.get('/').status_code == 200
    assert client.get('/', headers={"Host": "attacker.example"}).status_code == 400
    assert client.post('/api/action', json={"action":"connect", "mode":"simulator"}).status_code == 403
    headers = {"X-Diagnostics-Token": app.extensions["api_token"]}
    assert client.post('/api/action', json={"action":"clear_codes"}, headers=headers).status_code == 400
    assert client.post('/api/action', json={"action":"connect", "mode":"bogus"}, headers=headers).status_code == 400
    assert client.get('/api/recordings/missing/csv').status_code == 404
    assert client.get('/api/faults/report').status_code == 404
    assert client.post('/api/action', json={"action":"connect", "mode":"simulator"}, headers=headers).status_code == 202
    app.extensions["diagnostics"].tick()
    assert client.get('/api/status').json['mode'] == 'simulator'


def test_http_fault_report_and_recording_export(app):
    client = app.test_client()
    engine = app.extensions['diagnostics']
    engine.act('connect', {'mode':'simulator'})
    engine.act('faults', {})
    report = client.get('/api/faults/report')
    assert report.json['source_mode'] == 'simulator'
    assert report.json['results']['stored']['codes'][0][0] == 'P0101'
    engine.act('record_start', {})
    engine.tick()
    session = engine.recording
    engine.act('record_stop', {})
    assert client.get('/api/recordings').json[0]['samples'] == 1
    assert b'simulator' in client.get(f'/api/recordings/{session}/csv').data


def test_simulator_values_are_finite():
    values = Simulator().read()
    assert set(values) == {s.key for s in SENSORS}
    assert all(isinstance(v, (int,float)) for v in values.values())


def test_recording_disk_error_still_closes_backend(tmp_path, monkeypatch):
    engine = Engine(Store(tmp_path))
    engine.act('connect', {'mode': 'simulator'})
    engine.act('record_start', {})
    def failed(*args):
        raise OSError('Disk unavailable')
    monkeypatch.setattr(engine.store, 'append', failed)
    monkeypatch.setattr(engine.store, 'finish', failed)
    engine.tick()
    assert engine.backend is None and engine.recording is None
    assert engine.snapshot()['mode'] == 'disconnected'
    assert 'Disk unavailable' in engine.snapshot()['error']


def test_api_rejects_malformed_types(app):
    client = app.test_client()
    headers = {'X-Diagnostics-Token': app.extensions['api_token']}
    for key in ('port', 'baudrate'):
        response = client.post('/api/action', json={'action':'connect', 'mode':'vehicle', key:['bad']}, headers=headers)
        assert response.status_code == 400
