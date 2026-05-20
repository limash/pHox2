---
description: "Use when implementing, extending, or writing standalone Python modules for pH or CO3 seawater instruments. Covers hardware abstraction, measurement physics, measurement cycle, data formats, configuration schema, and quality control. Do NOT use for GUI work."
---

# CO3 (and future pH) Instrument Logic

## Overview

The system measures seawater pH and/or carbonate ion concentration (CO3²⁻) using spectrophotometric dye injection. It runs on a Raspberry Pi and interfaces with a Ferrybox flow-through system.

**Currently implemented**: CO3 instrument only. pH instrument support is planned and the physics/config sections for pH are retained for future implementation.

---

## Architecture

The codebase follows dependency inversion and interface-segregation principles. No class ever imports a concrete hardware driver directly — all dependencies are injected as abstractions.

```
configs/config.yaml              ← Hydra/OmegaConf configuration
        │
InstrumentFactory.build_cycle()           ← wires concrete → abstract; selects mock vs. real
InstrumentFactory.build_ferrybox_client() ← selects FerryboxUDPClient or NullFerryboxClient
        │
CO3MeasurementCycle              ← orchestrates the measurement sequence
  ├── ISpectrometer
  ├── IValve
  ├── IWaterPump
  ├── IDyePump
  ├── IStirrer
  ├── ILightSource
  ├── IShutter
  ├── IDrain
  ├── ITemperatureSensor
  └── CO3Calculator
        │
CO3InstrumentAPI                 ← public surface used by GUI and scripts
  └── IFerryboxClient            ← UDP comm: FerryboxUDPClient | NullFerryboxClient | MockFerryboxClient
        │
FileStorage                      ← writes .spt / .evl / .log to disk (external)
```

**pH instrument** (future): will follow the same pattern with a `pHInstrumentAPI` and a `pHMeasurementCycle`.

---

## Configuration System

Config is loaded via **Hydra/OmegaConf** from `configs/config.yaml`. Access the config as a `DictConfig` object; pass it to `InstrumentFactory.build_cycle(cfg)`.

### `hardware` section

| Key | Type | Example | Description |
|-----|------|---------|-------------|
| `use_mock` | bool | `true` | Use mock hardware (dev/CI); set `false` on real Raspberry Pi |

### `gpio` section (BCM pin numbering)

| Key | Type | Example | Description |
|-----|------|---------|-------------|
| `valve_enable_pin` | int | `24` | Bistable valve enable pulse pin |
| `valve_ch1_pin` | int | `23` | Bistable valve channel 1 pin |
| `valve_ch2_pin` | int | `25` | Bistable valve channel 2 pin |
| `valve_toggle_duration_s` | float | `0.3` | Pulse duration to flip the bistable valve |
| `water_pump_pin` | int | `21` | Sample flush pump relay |
| `dye_pump_pin` | int | `19` | Dye solenoid pump relay |
| `stirrer_pin` | int | `20` | Magnetic stirrer relay |
| `drain_pin` | int | `16` | Drain valve relay |
| `air_pin` | int | `26` | Compressed-air pump relay (pushes liquid out during drain) |
| `light_pin` | int | `17` | UV lamp relay |
| `shutter_pin` | int | `27` | Mechanical shutter relay |

### `adc` section

| Key | Type | Example | Description |
|-----|------|---------|-------------|
| `temperature_channel` | int | `8` | ADC channel connected to the temperature probe |

### `temperature` section

| Key | Type | Example | Description |
|-----|------|---------|-------------|
| `calibration_coefficients` | list[float] | `[-1.234, 15.678]` | `[coef0, coef1]`; T_cuvette (°C) = coef[0] × voltage + coef[1] |
| `n_averages` | int | `3` | ADC readings to average per temperature sample |

### `spectrometer` section

| Key | Type | Example | Description |
|-----|------|---------|-------------|
| `integration_time_ms` | float | `18.0` | Initial integration time |
| `n_averages` | int | `6` | Spectra to average per reading |
| `light_threshold_counts` | int | `60000` | Target intensity counts for auto-adjust |
| `autoadjust.enabled` | bool | `true` | Whether to run auto-adjust before each measurement |
| `autoadjust.tolerance_fraction` | float | `0.05` | ±5% tolerance band around threshold |
| `autoadjust.max_iterations` | int | `20` | Binary-search iteration limit |
| `autoadjust.step_ms` | float | `500` | Integration-time step size (ms) |

### `co3` section

| Key | Type | Example | Description |
|-----|------|---------|-------------|
| `wavelength_1_nm` | float | `234.0` | Main absorbance peak (A1) |
| `wavelength_2_nm` | float | `250.0` | Secondary peak (A2) |
| `wavelength_3_nm` | float | `350.0` | Reference baseline (A3) |
| `dye` | str | `"Pb_perchlor"` | `"Pb_perchlor"` or `"Pb_chlor"` |

### `measurement` section

| Key | Type | Example | Description |
|-----|------|---------|-------------|
| `cuvette_volume_ml` | float | `16.0` | Cuvette volume (mL) |
| `dye_volume_per_shot_ml` | float | `0.03` | Volume per dye solenoid pulse (mL) |
| `dye_n_shots` | int | `6` | Solenoid pulses per injection event |
| `n_cycles` | int | `1` | Dye injection + absorbance cycles per measurement |
| `mix_time_s` | float | `10.0` | Stirring time after dye injection (s) |
| `wait_time_s` | float | `5.0` | Settling time after stirrer stops (s) |
| `pump_time_s` | float | `60.0` | Sample flush duration before measurement (s) |
| `drain_after` | bool | `true` | Drain cuvette after each measurement |
| `drain_time_s` | float | `60.0` | Drain + air-pump duration (s) |
| `time_acceleration` | float | `1.0` | Divide all `asyncio.sleep` durations by this; set >1 for fast mock runs |

### `ship` section

| Key | Type | Example | Description |
|-----|------|---------|-------------|
| `code` | str | `"NB"` | Ship/platform identifier included in every log row |

### `output` section

| Key | Type | Example | Description |
|-----|------|---------|-------------|
| `base_path` | str | `"~/co3_data"` | Root directory for `FileStorage` output |

### `ferrybox` section

| Key | Type | Example | Description |
|-----|------|---------|-------------|
| `enabled` | bool | `false` | Activate UDP Ferrybox communication; `false` → `NullFerryboxClient` |
| `host` | str | `"192.168.1.100"` | IP address or hostname of the Ferrybox |
| `ferrybox_port` | int | `5556` | UDP port the Ferrybox listens on (instrument → Ferrybox) |
| `local_port` | int | `5555` | Local UDP port to bind for receiving Ferrybox data (Ferrybox → instrument) |

`InstrumentFactory.build_ferrybox_client(cfg)` reads this section and returns either a `FerryboxUDPClient` or a `NullFerryboxClient` (when the section is absent or `enabled: false`).

---

### pH configuration (future)

The pH instrument will add the following config sections (not yet in `config.yaml`):

**`[pH]` section**

| Key | Type | Example | Description |
|-----|------|---------|-------------|
| `LED_SLOTS` | list[int] | `[12, 13, 19, 16]` | GPIO BCM pins for LED PWM (Blue, Orange, Red, spare) |
| `LED1` | int | `55` | Blue LED PWM duty cycle (0–100) |
| `LED2` | int | `55` | Orange LED PWM duty cycle (0–100) |
| `LED3` | int | `55` | Red LED PWM duty cycle (0–100) |
| `Default_DYE` | str | `"MCP"` | Indicator dye: `"MCP"` or `"TB"` |
| `wl_NIR` | int | `730` | NIR reference wavelength (nm) |
| `MCP_wl_HI` | int | `434` | MCP acid-form wavelength (nm) |
| `MCP_wl_I2` | int | `578` | MCP base-form wavelength (nm) |
| `TB_wl_HI` | int | `434` | TB acid-form wavelength (nm) |
| `TB_wl_I2` | int | `596` | TB base-form wavelength (nm) |

**`[TrisBuffer]` section (pH calibration)**

| Key | Type | Example | Description |
|-----|------|---------|-------------|
| `S_tris_buffer` | int | `35` | Salinity of Tris calibration solution |
| `T_tris_buffer` | int | `20` | Temperature of calibration solution (°C) |
| `Calibration_threshold` | float | `0.005` | Max acceptable |ΔpH| between measured and theoretical |
| `Calibration_pump_time` | int | `30` | Seconds to pump calibration solution |

### Temperature probe calibration

Loaded from `configs/temperature_sensors_config.json` (referenced via the `temperature.calibration_coefficients` key in `config.yaml`; JSON file used when multiple probes are available):
```json
{
  "Probe_1": {
    "is_calibrated": "True",
    "Calibr_coef": [-1.234, 15.678]
  }
}
```
`T_cuvette = coef[0] * voltage + coef[1]` (°C)

---

## Hardware Interfaces

Hardware is accessed exclusively through abstract interfaces defined in `co3_instrument.components.interfaces` and `co3_instrument.hardware.interfaces`. Concrete implementations live under `hardware/mock/` and `hardware/real/`; `InstrumentFactory` selects between them based on `hardware.use_mock`.

### Component interfaces (`co3_instrument.components.interfaces`)

```python
class IValve(ABC):
    async def open(self) -> None   # open inlet (sample flows in)
    async def close(self) -> None  # close inlet (sample isolated)

class IWaterPump(ABC):
    async def run(self, duration_s: float) -> None

class IDyePump(ABC):
    async def pulse(self, n_shots: int) -> None

class IStirrer(ABC):
    def start(self) -> None
    def stop(self) -> None

class ILightSource(ABC):
    def turn_on(self) -> None
    def turn_off(self) -> None

class IShutter(ABC):
    def open(self) -> None
    def close(self) -> None

class IDrain(ABC):
    async def drain(self, duration_s: float) -> None

class ITemperatureSensor(ABC):
    def read_voltage(self) -> float
    def read_temperature(self) -> float  # °C
```

### Hardware layer (`co3_instrument.hardware.interfaces`)

```python
class ISpectrometer(ABC):
    def get_wavelengths(self) -> np.ndarray          # (n_pixels,) nm
    async def get_intensities(self) -> np.ndarray    # (n_pixels,) counts
    def set_integration_time(self, ms: float) -> None
    def reset_measurement_state(self) -> None

class IDigitalOutput(ABC):
    def write(self, pin: int, value: bool) -> None

class IAnalogInput(ABC):
    def read_voltage(self, channel: int) -> float
```

### Real hardware (when `use_mock: false`)

| Abstraction | Concrete class | Underlying library |
|-------------|---------------|-------------------|
| `ISpectrometer` | `SeabreezeSpectrometer` | `seabreeze` |
| `IDigitalOutput` | `PigpioDigitalOutput` | `pigpio` |
| `IAnalogInput` | `ADCDifferentialPiReader` | `ADCDifferentialPi` (I²C, 14-bit) |

The GUI and measurement cycle **never** import `pigpio`, `seabreeze`, or `ADCDifferentialPi` directly.

---

## Data Models

`MeasurementResult` (frozen dataclass) is the primary DTO returned by `CO3InstrumentAPI.run_single_measurement()`:

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | `datetime` | Cycle start time |
| `ship_code` | `str` | From `ship.code` config key |
| `co3_umol_per_kg` | `float` | Final CO3²⁻ concentration (µmol/kg) |
| `t_cuvette` | `float` | Cuvette temperature at measurement (°C) |
| `salinity_input` | `float` | Salinity before dilution correction |
| `salinity_corrected` | `float` | Salinity after dilution correction |
| `voltage` | `float` | Raw ADC voltage |
| `a1`, `a2`, `a3` | `float` | Absorbance at λ1, λ2, λ3 |
| `r_ratio` | `float` | `(A2−A3)/(A1−A3)` |
| `e1`, `e3e2`, `log_beta1_e2` | `float` | Chemistry coefficients |
| `vol_injected_ml` | `float` | Cumulative dye volume injected (mL) |
| `dye` | `str` | Dye name from config |
| `injections` | `tuple[InjectionResult, …]` | One per injection cycle |
| `spectra` | `SpectralData` | Raw intensity arrays |

`SpectralData` fields: `wavelengths` (nm array), `dark` (counts), `blank` (counts), `injections: dict[int, np.ndarray]` (keyed by 0-based injection index).

`InjectionResult` has the same chemistry fields as above, plus `injection_index` and `dilution`.

---

## Measurement Cycle (both instruments)

The full cycle is implemented as an async workflow in `CO3MeasurementCycle.run()`. Steps in order:

```
0. [Optional] Flush sample — run water pump for pump_time_s seconds
1. Close inlet valve
2. Auto-adjust integration time (binary search, if autoadjust.enabled)
3. Dark measurement — close shutter, capture spectrum, open shutter
4. Blank measurement — capture spectrum with clean water, no dye
5. For n in range(n_cycles):
   a. Start stirrer
   b. Inject dye: dye_n_shots pulses
   c. Mix: sleep mix_time_s seconds
   d. Stop stirrer
   e. Wait: sleep wait_time_s seconds
   f. Read temperature voltage (ADC, n_averages)
   g. Capture post-injection spectrum
   h. Calculate absorbance spectrum
   i. Calculate CO3 (or pH for future pH instrument)
6. [if drain_after] Drain cuvette — drain + air pump for drain_time_s seconds
7. Open inlet valve
8. Build and return MeasurementResult
```

File saving (`FileStorage.save(result)`) is the caller's responsibility; the cycle does not write to disk.

`time_acceleration` divides all `asyncio.sleep` durations — set >1 for fast mock testing.

---

## Absorbance Calculation (shared)

```python
absorbance_spectrum = -np.log10(
    (postinjection_spectrum - dark) / (blank - dark)
)
```
Absorbance at 3 wavelengths (λ1, λ2, λ3) is extracted at the resolved pixel indices.

Pixel index resolution: `CO3Calculator.find_pixel(wavelengths, target_nm)` → `np.abs(wavelengths - target_nm).argmin()`

---

## pH Instrument — Physics

### Dye selection and wavelengths

| Dye | A1 wavelength | A2 wavelength | NIR reference |
|-----|--------------|--------------|--------------|
| MCP (m-Cresol Purple) | 434 nm | 578 nm | 730 nm |
| TB (Thymol Blue) | 434 nm | 596 nm | 730 nm |

### Dilution correction (per injection cycle)

```python
vol_injected = DYE_V_INJ * (n_inj + 1) * nshots   # mL cumulative
dilution = CUVETTE_V / (vol_injected + CUVETTE_V)   # dimensionless, < 1
S_corr = salinity * dilution
```

### Absorbance ratio

```python
R = A2 / A1
```

### pH with MCP dye (Clayton & Byrne 1993 + Liu et al. 2011)

```python
T = 273.15 + T_cuvette   # Kelvin
e1 = -0.007762 + (4.5174e-5) * T
e2e3 = -0.020813 + (2.60262e-4 * T) + (1.0436e-4) * (S_corr - 35)
arg = (R - e1) / (1 - R * e2e3)
pK = (5.561224
      - 0.547716 * S_corr**0.5
      + 0.123791 * S_corr
      - 0.0280156 * S_corr**1.5
      + 0.00344940 * S_corr**2
      - 0.000167297 * S_corr**2.5
      + (52.640726 * S_corr**0.5) / T
      + 815.984591 / T)
pH = pK + np.log10(arg)   # guard: only if arg > 0, else pH = 99.9999
```
Note: for log file compatibility `e2` and `e3` are stored as `e2e3` and `-99` respectively.

### pH with TB dye

```python
T = 273.15 + T_cuvette
e1 = -0.00132 + 1.6e-5 * T
e2 = 7.2326 - 0.0299717 * T + 4.6e-5 * (T**2)
e3 = 0.0223 + 0.0003917 * T
pK = 4.706 * (S_corr / T) + 26.3300 - 7.17218 * np.log10(T) - 0.017316 * S_corr
arg = (R - e1) / (e2 - R * e3)
pH = 0.0047 + pK + np.log10(arg)
```

### Multi-injection regression (final pH)

After `ncycles` (default 4) injections:

```python
dpH_dT = -0.0155  # pH / °C

# Temperature-drift correction (reference = T of first injection)
T_ref = evalPar_df["T_cuvette"][0]
pH_t_corr = evalPar_df["pH"] + dpH_dT * (T_ref - evalPar_df["T_cuvette"])

x = evalPar_df["Vol_injected"].values   # volume axis
y = pH_t_corr.values
```

Regression logic:
- If `std(y) <= 0.001`: `pH_cuvette = mean(y)`, `slope = 0`, `r_value = 0`
- If `std(y) > 0.001`: fit all 4 points, then try removing first and last point; keep the fit with the highest r². Use intercept as `pH_cuvette`.

In-situ pH correction to Ferrybox seawater temperature:
```python
pH_insitu = pH_cuvette + dpH_dT * (T_ferrybox - T_cuvette)
```

### Theoretical Tris buffer pH (for calibration)

```python
T_K = T_cuvette + 273.15
S = 35  # Tris buffer salinity
pH_tris = ((11911.08 - 18.2499*S - 0.039336*S**2) / T_K
           - 366.27059 + 0.53993607*S + 0.00016329*S**2
           + (64.52243 - 0.084041*S) * np.log(T_K)
           - 0.11149858 * T_K)
```

### LED auto-adjustment (pH)

Target: `THR * 0.95 < pixel_level < THR * 1.05`  
For each LED (0=Blue, 1=Orange, 2=Red):
1. Binary search on PWM duty cycle (0–100), increment halved on direction change
2. If pixel too high and LED at minimum (≤15): flag "decrease int time"
3. If pixel too low and LED at maximum (≥90): flag "increase int time"
4. If any LED signals int time change: adjust `specIntTime` by `increment_sptint` (starts at 200 ms, halved on direction reversal)
5. `autoadj_opt == 'ON_NORED'`: skip Red LED adjustment, force to 99

---

## CO3 Instrument — Physics

### Dye and wavelengths

Dye: lead perchlorate (Pb(ClO4)₂), UV-absorbing.

| Symbol | Wavelength | Role |
|--------|-----------|------|
| A1 | 234 nm | Main peak |
| A2 | 250 nm | Secondary peak |
| A3 | 350 nm | Reference (baseline) |

### Absorbance ratio

```python
R = (A2 - A3) / (A1 - A3)
```

### CO3²⁻ calculation (Sharp & Byrne 2019; valid for 17 < S < 40)

```python
S = S_corr  # dilution-corrected salinity
T = T_cuvette  # °C

e1 = (1.09519e-1 + 4.49666e-3*S + 1.95519e-3*T
      + 2.44460e-5*T**2 - 2.01796e-5*S*T)

e3e2 = (32.4812e-1 - 79.7676e-3*S + 6.28521e-4*S**2
        - 11.8691e-3*T - 3.58709e-5*T**2 + 32.5849e-5*S*T)

log_beta1_e2 = (55.6674e-1 - 51.0194e-3*S + 4.61423e-4*S**2
                - 13.6998e-5*S*T)

arg = (R - e1) / (1 - R * e3e2)
CO3 = 1.0e6 * (10 ** -(log_beta1_e2 + np.log10(arg)))  # µmol/kg
```

### Final CO3 value

With `n_cycles = 1` (current default), `CO3` is taken directly from the single `InjectionResult`. With `n_cycles > 1`, the mean CO3 across injections is used. The final value is stored in `MeasurementResult.co3_umol_per_kg`.

### Light source (UV lamp)

- Relay-controlled; must warm up ~3 minutes before measurement
- Shutter (`IShutter`) blocks light during dark measurement
- Dark: `shutter.close()` → capture → `shutter.open()`
- Auto-adjust: integration time only (no lamp power control), same binary-search algorithm as pH but targets the configured `light_threshold_counts`

### Drain sequence

Handled by `IDrain.drain(duration_s)`. Internally activates drain relay then air-pump relay for `drain_time_s` seconds, then releases both.

---

## Salinity Source

Priority order:
1. Manual input (used for single/manual measurements; not for continuous or calibration)
2. Calibration mode: always uses `TrisBuffer.S_tris_buffer` (= 35)
3. Continuous mode: `api.get_ferrybox_data().salinity` (real-time from `IFerryboxClient`; requires `ferrybox.enabled: true`)

---

## UDP Communication (`phox2.communication`)

Ferrybox communication is fully implemented using `asyncio.DatagramProtocol` with dependency injection. All classes are in `src/phox2/communication/`.

### Abstractions (`communication/interfaces.py` and `communication/models.py`)

**`IFerryboxClient`** (abstract base class) — the only type the instrument APIs (`CO3InstrumentAPI`, `pHInstrumentAPI`) ever reference:

| Method | Signature | Description |
|--------|-----------|-------------|
| `start` | `async () → None` | Bind UDP socket and begin listening |
| `stop` | `async () → None` | Close UDP socket and release resources |
| `get_latest_data` | `() → FerryboxData \| None` | Sync read of last received packet (no I/O) |
| `send_result` | `async (IUDPPayload) → None` | Serialise and transmit result to Ferrybox (fire-and-forget) |

**`FerryboxData`** (frozen dataclass) — represents one received Ferrybox packet:

| Field | Type | Description |
|-------|------|-------------|
| `salinity` | `float` | In-situ salinity (PSU) |
| `timestamp` | `datetime` | UTC time the packet was received |
| `temperature` | `float \| None` | Optional sea-surface temperature (°C) |

**`IUDPPayload`** (runtime-checkable Protocol) — any measurement result that implements `to_udp_payload() → dict` satisfies this; no inheritance needed.

### Concrete classes (`communication/udp_client.py`)

**`FerryboxUDPClient`** — real asyncio UDP implementation:
- Constructor: `FerryboxUDPClient(ferrybox_host, ferrybox_port, local_port)`
- Binds `0.0.0.0:{local_port}` for incoming Ferrybox packets; sends to `{ferrybox_host}:{ferrybox_port}`
- Incoming packet format (UTF-8 JSON, newline-delimited):
  ```json
  {"type": "ferrybox_data", "salinity": 35.012, "temperature": 18.5}
  ```
  Packets with a missing or non-`"ferrybox_data"` `type` field are silently discarded.
  `temperature` is optional; missing/malformed values are treated as `None`.
- Outgoing: `json.dumps(result.to_udp_payload()) + "\n"` sent to the Ferrybox. Errors are logged but not raised.

**`NullFerryboxClient`** — no-op used when `ferrybox.enabled: false`. All methods do nothing; `get_latest_data()` always returns `None`.

### Mock classes (`communication/mock/`)

**`MockFerryboxClient`** (`mock/client.py`) — in-memory stub for unit tests. Constructor: `MockFerryboxClient(preset_data=None)`. Attributes: `sent_payloads: list[dict]`, `started: bool`, `stopped: bool`. Use `set_preset_data(data)` to change the value returned by `get_latest_data()` at runtime.

**`MockFerryboxDevice`** (`mock/device.py`) — async UDP server that simulates the *Ferrybox side*. Broadcasts synthetic `ferrybox_data` JSON packets at a configurable interval and collects result datagrams sent by the instrument into `received_results: list[dict]`. Run as a standalone process with `python -m phox2.communication.mock.device`.

### Factory wiring

`InstrumentFactory.build_ferrybox_client(cfg)` returns:
- `FerryboxUDPClient(host, ferrybox_port, local_port)` when `ferrybox.enabled: true`
- `NullFerryboxClient()` when the `ferrybox` section is absent or `enabled: false`

### Integration in `CO3InstrumentAPI`

| Lifecycle hook | Action |
|----------------|--------|
| `connect()` | `await self._ferrybox.start()` |
| `disconnect()` | `await self._ferrybox.stop()` |
| `run_single_measurement()` | `await self._ferrybox.send_result(result)` after the cycle completes |
| `get_ferrybox_data()` | `return self._ferrybox.get_latest_data()` (sync) |

---

## Data Files and Formats

Files are written by `FileStorage(base_path)`. Base directory comes from `output.base_path` in config (e.g. `~/co3_data`).

### SPT file (spectrum data)
Path: `{base}/data_co3/spt/{timestamp}.spt`  
Format: transposed CSV. Rows = named columns (`Wavelengths`, `dark`, `blank`, `0`, `1`, …). Columns = pixel indices. Written via `DataFrame.T.to_csv(path, index=True, header=False)`.

### EVL file (intermediate evaluation, per injection)

**CO3 EVL columns** (`{base}/data_co3/evl/{timestamp}.evl`):
```
CO3, e1, e3e2, log_beta1_e2, Voltage, S, A1, A2, R, T_cuvette,
Vol_injected, S_corr, A350
```

**pH EVL columns** (future, `{base}/data_pH/evl/{timestamp}.evl`):
```
pH, pK, e1, e2, e3, Voltage, salinity, A1, A2, T_cuvette, S_corr, Anir,
Vol_injected, TempProbe_id, Probe_iscalibr, TempCalCoef1, TempCalCoef2, DYE
```

### Log file (one row per final measurement)

**CO3 log** (`{base}/data_co3/CO3.log`), columns written by `FileStorage._append_log`:
```
Time, SHIP, co3, T_cuvette, S_input, S_corr, voltage, A1, A2, A3, R, dye
```

**pH log** (future, `{base}/data_pH/pH.log`):
```
Time, Lon, Lat, fb_temp, fb_sal, SHIP, pH_cuvette, T_cuvette,
perturbation, evalAnir, pH_insitu, r_square, box_id
```

Calibration logs go to `{base}/data_pH_calibr/pH_cal.log` (same columns + `cal_result`, `difference`, `Buffer_theoretical_val`, `Buffer_temp`, `batch_number`).

### JSON upload (pH only, future)
Path: `{base}/data_pH/upload/{timestamp}.json`
```json
{
  "spt": { "<col_name>": [values...] },
  "eval": { "<col_name>": [values...] },
  "final_pH": { "<col_name>": scalar }
}
```

### Timestamp format
```python
result.timestamp.strftime("%Y%m%d_%H%M%S")       # filename stem
result.timestamp.strftime("%Y-%m-%d_%H:%M")        # in log rows
```

---

## Quality Control Checks (after each measurement)

> **Not yet in `MeasurementResult`** — QC flags are planned but not currently stored in the data model or log. The logic below defines the intended checks.

| QC flag | Logic |
|---------|-------|
| Flow | `(blue_pixel_after_last_injection − blue_pixel_before_last_injection) > flow_threshold` |
| Dye | `mean(blank − inj_0) > 5` counts |
| Biofouling | spectrometer integration time < 2 000 ms |
| Temp sensor | Not all ADC voltage readings identical |
| UDP | `udp.FERRYBOX['pumping'] is not None` (future, requires UDP module) |

`flow_threshold` is a future config key (suggested default: 2 000 counts).

---

## Output Precision

Suggested decimal places for formatted output:

| Field | Decimals |
|-------|----------|
| pH | 4 |
| co3 (µmol/kg) | 1 |
| e1, e2, e3 | 6 |
| A1, A2, A3 | 5 |
| voltage | 5 |
| salinity | 2 |
| T_cuvette | 3 |
| vol_injected | 2 |
| latitude, longitude | 6 |

---

## Building a Standalone Module — Checklist

To implement a standalone (GUI-free) module for the CO3 instrument:

1. **Load config**: `cfg = OmegaConf.load("configs/config.yaml")`
2. **Build API** (preferred): `api = CO3InstrumentAPI.from_config(cfg)` — wires hardware, calculator, **and** Ferrybox client automatically
3. **Connect**: `await api.connect()` (resolves pixel indices; starts Ferrybox UDP socket if enabled; idempotent)
4. **Salinity**: pass manually, or read from `api.get_ferrybox_data().salinity` when `ferrybox.enabled: true`
5. **Run measurement**: `result = await api.run_single_measurement(salinity, flush_before=True)`
6. **Save**: `FileStorage(cfg.output.base_path).save(result)`
7. **Disconnect**: `await api.disconnect()` (stops Ferrybox UDP socket)

Use the async context manager for safe resource handling:
```python
async with CO3InstrumentAPI.from_config(cfg) as api:
    result = await api.run_single_measurement(35.0, flush_before=True)
```

Alternatively, wire pieces manually (e.g. for testing with a mock Ferrybox client):
```python
cycle = InstrumentFactory.build_cycle(cfg)
ferrybox = MockFerryboxClient(preset_data=FerryboxData(salinity=35.0, timestamp=datetime.now()))
api = CO3InstrumentAPI(cycle, ferrybox_client=ferrybox)
```

---

## CO3InstrumentAPI — Method Reference

| Method | Sync/Async | Description |
|--------|-----------|-------------|
| `await connect()` | async | Initialise hardware; resolve pixel indices |
| `await disconnect()` | async | Safe shutdown (open valve, turn off light) |
| `await run_single_measurement(salinity, flush_before)` | async | Full CO3 measurement cycle |
| `await get_spectrum()` | async | Single spectrum capture (live display) |
| `get_temperature()` | sync | Current cuvette temperature (°C) |
| `get_ferrybox_data()` | sync | Latest `FerryboxData` from Ferrybox, or `None` if none received yet |
| `await open_valve()` | async | Open inlet valve |
| `await close_valve()` | async | Close inlet valve |
| `turn_on_light()` | sync | Switch UV lamp on |
| `turn_off_light()` | sync | Switch UV lamp off |
| `open_shutter()` | sync | Open optical shutter |
| `close_shutter()` | sync | Close optical shutter |
| `await run_water_pump(duration_s)` | async | Run water pump for N seconds |
| `await pulse_dye_pump(n_shots)` | async | Fire dye solenoid N times |
| `start_stirrer()` | sync | Energise stirrer |
| `stop_stirrer()` | sync | De-energise stirrer |
| `await drain_cuvette(duration_s=None)` | async | Drain cuvette (defaults to `drain_time_s` from config) |
| `await auto_adjust_integration_time()` | async | Binary-search integration time to hit threshold |
| `wavelengths` | property | Spectrometer wavelength array (nm); available after connect |

---

## References

- Clayton, T.D. & Byrne, R.H. (1993). Spectrophotometric seawater pH measurements. *Deep-Sea Research I*, 40(10), 2115–2129. (MCP dye)
- Liu, X., Patsavas, M.C., Byrne, R.H. (2011). Purification and characterization of meta-cresol purple for spectrophotometric seawater pH measurements. *Environ. Sci. Technol.*, 45(11), 4862–4868.
- Sharp, J.D. & Byrne, R.H. (2019). Carbonate ion concentrations in seawater: spectrophotometric determination. *Anal. Chim. Acta*, 1062, 45–56. (CO3 Sharp & Byrne 2019)
- Patsavas, M.C. et al. (2015). Spectrophotometric determination of carbonate ion in seawater. *Mar. Chem.*, 168, 80–89.
