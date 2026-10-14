# Architecture and extension boundary

`backends.py` defines the `Backend` protocol, explicit sensor metadata, `Vehicle` and `Simulator`. `Vehicle` is the sole location issuing OBD requests. It only queries a fixed read-only sensor set plus stored/pending DTC modes. No arbitrary serial-command HTTP endpoint exists.

`engine.py` owns all serial operations on one background thread. HTTP mutations enter a bounded queue and return 202, meaning accepted rather than completed; clients inspect the status/error snapshot for the outcome. Snapshots are copied under a lock. Source changes close the prior source and end recordings. Multiple browsers observe the same engine. The worker polls once per completed cycle plus 0.5 seconds, so the serial transport determines actual frequency.

`storage.py` stores sessions and append-only samples in SQLite, one committed transaction per frame, with source provenance and sensor units. Export streams rows; replay iterates rows, using a monotonic clock to preserve original timing without loading an entire session into memory. Sample values may be null. Timestamps are UTC ISO 8601.

`web.py` serves local static assets and JSON/CSV APIs. It validates known actions, serial port membership, baud rates, request size, host names and a per-process anti-CSRF header. It never accepts arbitrary file paths from the browser. This is a single-user local service, not an authenticated public application.

## Future manufacturer support

Add a separate backend that implements `read`, `faults`, `close`, `mode` and declared `sensors`. Before integrating it, add explicit identity and capability metadata (manufacturer, supported model/year/ECU/protocol, transport, read versus write privileges), fixtures from documented real hardware sessions and a coverage entry. Keep manufacturer operations outside the standard OBD-II backend; do not infer support from brand name, adapter CAN capability or simulator results.

Ford network switching, manufacturer DIDs, Fiat/Suzuki-specific services, ECU addressing and write/service workflows need independent research and validation. The current extension boundary is code-level, not a plugin loader. No manufacturer-specific functionality is currently implemented. New source modes will require corresponding UI/provenance changes and tests.

## Known limits

No automatic reconnect, replay seeking/pause, CSV import, DTC recording timeline, authentication, chart persistence across browser reloads or simultaneous adapters. Sensor discovery currently uses python-OBD's supported-command set from the selected connection; it is not a per-ECU inventory. Shutdown waits for serial work to complete within a bounded interval. A forced process exit may leave a session marked open; committed frames remain recoverable.
