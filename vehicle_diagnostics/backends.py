"""Read-only backend boundary. Manufacturer extensions must declare their coverage."""
from dataclasses import asdict, dataclass
import math
import time
from typing import Protocol


@dataclass(frozen=True)
class Sensor:
    key: str
    label: str
    unit: str
    command: str
    source: str = "ECU"


SENSORS = [
    Sensor("rpm", "Engine speed", "rpm", "RPM"),
    Sensor("speed", "Road speed", "km/h", "SPEED"),
    Sensor("coolant", "Coolant temperature", "°C", "COOLANT_TEMP"),
    Sensor("load", "Engine load", "%", "ENGINE_LOAD"),
    Sensor("maf", "Airflow", "g/s", "MAF"),
    Sensor("intake", "Intake pressure", "kPa", "INTAKE_PRESSURE"),
    Sensor("voltage", "Control module voltage", "V", "CONTROL_MODULE_VOLTAGE"),
    Sensor("adapter_voltage", "Adapter supply voltage", "V", "ELM_VOLTAGE", "adapter"),
    Sensor("fuel", "Fuel pressure", "kPa", "FUEL_PRESSURE"),
    Sensor("rail", "Diesel / direct injection rail pressure", "kPa", "FUEL_RAIL_PRESSURE_DIRECT"),
]
UNITS = {"rpm": "rpm", "km/h": "kph", "°C": "degC", "%": "percent",
         "g/s": "gram / second", "kPa": "kilopascal", "V": "volt"}


class Backend(Protocol):
    mode: str
    sensors: list[Sensor]

    def read(self) -> dict: ...
    def faults(self) -> dict: ...
    def close(self) -> None: ...


def catalog(sensors):
    return [asdict(s) for s in sensors]


def ports():
    from serial.tools.list_ports import comports
    return [{"device": p.device, "description": p.description, "hwid": p.hwid}
            for p in comports()]


class Simulator:
    mode = "simulator"
    sensors = SENSORS

    def __init__(self):
        self.started = time.monotonic()

    def read(self):
        t = time.monotonic() - self.started
        wave = (math.sin(t / 8) + 1) / 2
        return dict(zip([s.key for s in self.sensors], [
            round(800 + 2300 * wave), round(70 * wave, 1), round(78 + 8 * wave, 1),
            round(20 + 60 * wave, 1), round(8 + 70 * wave, 1), round(100 + 80 * wave, 1),
            14.2, 14.1, 300.0, round(28000 + 90000 * wave, 1)]))

    def faults(self):
        return {"stored": {"status": "ok", "codes": [["P0101", "SIMULATED: Mass air flow range/performance"]]},
                "pending": {"status": "ok", "codes": []}}

    def close(self):
        pass


class Vehicle:
    mode = "vehicle"

    def __init__(self, port=None, baudrate=None, factory=None):
        import obd
        self.obd = obd
        self.connection = (factory or obd.OBD)(portstr=port, baudrate=baudrate,
                                               fast=False, timeout=3)
        if not self.connection.is_connected():
            status = str(self.connection.status())
            self.connection.close()
            raise ConnectionError(f"Vehicle not connected ({status}). Check ignition, cable and serial permissions.")
        self.sensors = [s for s in SENSORS if self.connection.supports(getattr(obd.commands, s.command))]
        self.supported_commands = sorted(c.name for c in self.connection.supported_commands)
        self.protocol = self.connection.protocol_name()
        self.empty_cycles = 0

    def read(self):
        if not self.connection.is_connected():
            raise ConnectionError("Adapter disconnected. Reconnect explicitly when ready.")
        values = {}
        ecu_values = []
        for s in self.sensors:
            response = self.connection.query(getattr(self.obd.commands, s.command))
            value = None
            if not response.is_null():
                value = float(response.value.to(UNITS[s.unit]).magnitude)
                if not math.isfinite(value):
                    value = None
            values[s.key] = value
            if s.source == "ECU":
                ecu_values.append(value)
        self.empty_cycles = self.empty_cycles + 1 if ecu_values and all(v is None for v in ecu_values) else 0
        if self.empty_cycles >= 3:
            raise ConnectionError("ECU stopped returning data for three polling cycles. Check ignition and reconnect.")
        return values

    def faults(self):
        result = {}
        for label, name in [("stored", "GET_DTC"), ("pending", "GET_CURRENT_DTC")]:
            # These modes are queried explicitly: PID discovery does not establish DTC-mode support.
            response = self.connection.query(getattr(self.obd.commands, name), force=True)
            result[label] = {"status": "no_response" if response.is_null() else "ok",
                             "codes": [] if response.is_null() else response.value}
        return result

    def close(self):
        self.connection.close()
