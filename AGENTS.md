---
description: Project-specific coding conventions, architecture invariants, and build commands for the phox2 seawater instrument codebase. Load when writing, reviewing, or refactoring any Python module in this repo.
---

# phox2 — Project Guidelines

Standalone Python module for pH and CO3 seawater spectrophotometric measurement on a Raspberry Pi / Ferrybox system.

---

## Architecture Invariants (SOLID)

These rules are non-negotiable. Violating them breaks the mock/real hardware swap.

### Dependency Inversion — never import concrete hardware directly

All hardware is accessed through abstract interfaces only:
- `hardware/interfaces.py` — `IDigitalOutput`, `IAnalogInput`, `IPWMOutput`, `ISpectrometer`
- `components/interfaces.py` — `IValve`, `IWaterPump`, `IDyePump`, `IStirrer`, `ILightSource`, `IShutter`, `IDrain`, `ITemperatureSensor`
- `communication/interfaces.py` — `IFerryboxClient`

Concrete implementations live under `hardware/mock/`, `hardware/real/`, and `communication/`. **Only `InstrumentFactory` (`factory.py`) ever imports concrete classes.**

### Factory is the wiring point

`InstrumentFactory` is the single place that selects mock vs. real hardware and wires concrete → abstract. Nothing else should instantiate `MockDigitalOutput`, `PigpioDigitalOutput`, etc.

### Public API is the entry point

GUI, scripts, and tests interact with the instrument exclusively through:
- `CO3InstrumentAPI` (`co3_api.py`)
- `pHInstrumentAPI` (`ph_api.py`)

Never access `CO3MeasurementCycle` or hardware components from outside those API classes.

---

## Module Map

```
src/phox2/
  hardware/         # ABCs + mock/ and real/ concrete drivers
  components/       # Higher-level component wrappers (valve, pump, etc.) built on hardware ABCs
  measurement/      # Cycle orchestration (co3_cycle.py, ph_cycle.py) + frozen dataclass models
  physics/          # Pure functions: CO3 and pH calculations (no I/O, no hardware)
  communication/    # IFerryboxClient ABC + FerryboxUDPClient / NullFerryboxClient
  storage/          # FileStorage — writes .spt / .evl / .log files
  gui/              # FastAPI + WebSocket server; calls API classes only
  factory.py        # InstrumentFactory — only wiring point
  co3_api.py        # CO3InstrumentAPI — public surface
  ph_api.py         # pHInstrumentAPI — public surface
configs/            # co3_config.yaml, ph_config.yaml (Hydra/OmegaConf)
tests/              # pytest-asyncio integration tests using mock hardware
```

---

## Key Conventions

### Configuration
- Config loaded via **Hydra/OmegaConf** (`DictConfig`). Pass `cfg` to `InstrumentFactory`, never parse it inside components.
- `hardware.use_mock: true` enables full mock mode (CI, dev). `false` requires real RPi drivers.
- `measurement.time_acceleration` divides all `asyncio.sleep` durations — set high in tests.

### Data models
- Measurement results are **frozen dataclasses** (`@dataclass(frozen=True)`) — never mutate after creation.
- `CO3MeasurementResult` and `pHMeasurementResult` are the primary DTOs; `SpectralData` carries raw spectra.

### Async
- Measurement cycles and hardware calls are `async`. Never block the event loop with synchronous I/O.
- API classes are async context managers (`async with API.from_config(cfg) as api:`).
- `ISpectrometer.get_intensities()` is async; `get_intensities_sync()` exists for GUI polling.

### Interfaces (ISP)
- Each interface covers exactly one hardware role. Do not add unrelated methods to an existing interface.
- New hardware capabilities → new interface in the appropriate `interfaces.py`.

---

## Build and Test

```bash
# Install (dev mode, with dev extras)
pip install -e ".[dev]"

# Run tests (mock hardware, no RPi required)
pytest

# Run with time acceleration for fast CI
# Set measurement.time_acceleration: 100 in config
```

Tests load configs directly via `OmegaConf.load()` — no Hydra, no output directories created.

---

## Keep Instructions in Sync

When you change instrument logic or GUI design, update the matching instruction file **in the same task**.

| Change type | Instruction file |
|-------------|-----------------|
| Hardware interfaces, measurement physics, config schema, data models, API methods, communication | `.github/instructions/instrument-logic.instructions.md` |
| GUI layout, tabs, plots, live data, manual controls, mode state machine | `.github/instructions/gui-design.instructions.md` |

If a change makes a section stale or wrong, rewrite it. If it adds a new subsystem, add a matching section.
