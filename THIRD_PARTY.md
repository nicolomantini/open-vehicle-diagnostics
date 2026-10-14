# Upstream review — 2026-10-14

## python-OBD

- Repository: https://github.com/brendan-w/python-OBD
- Licence: GNU GPL v2, https://github.com/brendan-w/python-OBD/blob/master/LICENSE
- Commands: https://python-obd.readthedocs.io/en/latest/Command%20Tables/
- Connections: https://python-obd.readthedocs.io/en/latest/Connections/
- Tested installed version: 0.7.3 (`obd` on PyPI); this is the application pin, not a claim that it is the newest release.

Provides ELM327 serial connections, automatic port/protocol discovery, supported-command discovery, unit-bearing sensor responses and DTC queries. Capability depends on the vehicle and adapter. This project uses its public API, without vendoring its source. It does not inherit comprehensive manufacturer diagnostics merely by using this library.

## pyOBD

- Repository and capability reference: https://github.com/barracuda-fsh/pyobd
- Licence file: https://github.com/barracuda-fsh/pyobd/blob/main/COPYING
- GitHub licence metadata was checked and reports GPL-2.0.

The current README describes a Python 3 desktop application using python-OBD, live sensors/graphs, trouble codes, tests and freeze frames. It reports the VGate vLinker FS USB among tested adapters. It describes engine-data coverage, excluding airbags/ABS/body systems, and says recording/replay is not available. Used only as a feature/interface reference; no code, artwork or assets copied.

## This application

Original application source is distributed under GPL-2.0-only, compatible with its GPL v2 communication dependency. Flask and transitive dependencies retain their own licences; they are installed through pip, not vendored. No remote JavaScript, font or chart dependencies are required. Review dependency licences again before distributing bundled binaries.
