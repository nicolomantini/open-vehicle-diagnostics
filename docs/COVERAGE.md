# Coverage and validation ledger

## Environment evidence

On 2026-10-14, `findmnt` identified `/dev/sda1` (ext4), and `lsblk` identified its parent as a 931.5 GiB USB disk. The system root was on `mmcblk0p2`, a separate SD card. The repository was created only on that external drive and renamed to `/mnt/external/Projects/open-vehicle-diagnostics` at the owner's request.

The actual development host reported Debian GNU/Linux 13, Python 3.13.5, ARM64. Ubuntu installation instructions are provided, but Ubuntu itself was not the local test host.

## Validation categories

| Target | Evidence | Result / limit |
| --- | --- | --- |
| Simulator | Automated backend, recording, CSV, replay and API tests | Synthetic values only; proves software behavior, not vehicle coverage |
| python-OBD adapter boundary | Mocked connection tests using actual command objects and Pint units | Discovery, nulls, conversion and errors; no serial hardware involved |
| vLinker FS USB | pyOBD upstream README reports adapter testing | Reference evidence only; untested with this application |
| Ford Transit 2011 2.2 T115 diesel | Intended first vehicle | No real-vehicle session; supported PIDs and protocol not yet confirmed |
| Fiat Sedici | Standard OBD-II target, year/engine unspecified | No real-vehicle session; exact ECU coverage unknown |
| ABS / SRS / coding / service functions | No implementation | Unsupported |

## Local software validation completed

- 14 pytest tests passed on Python 3.13.5.
- Editable installation and dependency consistency checked.
- Installed Chromium exercised simulator connection, ten rendered sensor charts, recording start/stop, a downloaded CSV containing simulator provenance, synthetic DTC reporting, timestamp-paced replay and disconnect; no JavaScript errors were observed.
- A 390-pixel phone viewport had no horizontal page overflow.
- The README screenshot is from that synthetic browser session, not a vehicle.

## First real-vehicle acceptance session

1. Park safely, connect the USB adapter, turn ignition on, select Vehicle mode and record OS, adapter model/firmware, vehicle year/engine and actual protocol.
2. Save the discovered command list. Confirm RPM reads zero with ignition on/engine off, coolant is plausible, and voltage channels are clearly distinguished. Treat a null as missing, not zero.
3. With the engine running in a ventilated location, compare RPM and temperatures with independent evidence. Record sensor values and export CSV. Do not infer pressure units from magnitudes; check the query and declared units.
4. Read stored/pending DTCs and save the report. A no-response category is inconclusive; an empty decoded list applies only to that category. Compare with a known diagnostic tool if available.
5. Stop recording and replay it with the adapter disconnected. Confirm source is `vehicle`, timestamps/units are retained and values match the CSV.
6. Test ignition loss and USB unplug recovery. Reconnect explicitly and check that old readings are cleared.
7. Add a dated evidence entry here, distinguishing observed behavior, unknowns and failures. Do not publish personally identifying recording data without reviewing it.
