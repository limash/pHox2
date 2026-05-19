---
description: "Use when implementing, extending, or writing standalone Python modules for pH or CO3 seawater instruments. Covers hardware abstraction, measurement physics, measurement cycle, data formats, configuration schema, and quality control. Do NOT use for GUI work."
---

# pHox / pCO3 Instrument Logic

## Overview

The system measures seawater pH and/or carbonate ion concentration (CO3²⁻) using spectrophotometric dye injection. It runs on a Raspberry Pi and interfaces with a Ferrybox flow-through system. The codebase decouples hardware/physics (`pHox.py`) from the PyQt5 GUI (`pHox_gui.py`). New standalone modules should only depend on `pHox.py`, `udp.py`, `util.py`, and `precisions.py`.

---

## Class Hierarchy

```
Spectro_seabreeze  |  Spectro_localtest      ← spectrometer abstraction
        └──────────────────┘
Common_instrument(panelargs)
├── pH_instrument(Common_instrument)
│   └── Test_pH_instrument(pH_instrument)    ← local dev mock
└── CO3_instrument(Common_instrument)
    └── Test_CO3_instrument(CO3_instrument)  ← local dev mock
```

Both instrument classes share fluidics, temperature measurement, ADC, and spectrometer via `Common_instrument`.

---

## Configuration System

Config is loaded from `~/box_id.txt` → `configs/config_{BOX_ID}.json`.  
`util.CONFIG_FILE` is a `dict` with sections: `Operational`, `pH`, `CO3`, `pCO2`, `TrisBuffer`, `QC`.

### `[Operational]` — Shared by both instruments

| Key | Type | Example | Description |
|-----|------|---------|-------------|
| `TEMP_PROBE_ID` | str | `"Probe_1"` | Which temp probe calibration entry to use |
| `T_PROBE_CH` | int | `8` | ADC channel for temperature probe |
| `WPUMP_SLOT` | int | `17` | GPIO BCM pin for water pump relay |
| `DYEPUMP_SLOT` | int | `18` | GPIO BCM pin for dye pump relay |
| `STIRR_SLOT` | int | `27` | GPIO BCM pin for stirrer relay |
| `SPARE_SLOT` | int | `22` | GPIO BCM pin for spare relay |
| `VALVE_SLOTS` | list[int] | `[24, 23, 25]` | Bistable valve GPIO pins: [enable, ch1, ch2] |
| `DYE_V_INJ` | float | `0.03` | Volume per dye pump shot (mL) |
| `CUVETTE_V` | int/float | `16` | Cuvette volume (mL) |
| `dye_nshots` | int | `1` (pH), `6` (CO3) | Dye pump pulses per injection event |
| `ncycles` | int | `4` (pH), `1` (CO3) | Dye injection cycles per measurement |
| `specAvScans` | int | `6` | Number of spectra to average per reading |
| `AUTOSTART` | str | `"True"` | Whether to autostart on boot |
| `AUTOSTART_MODE` | str | `"pump"` | `"pump"`, `"time"`, or `"now"` |
| `SAMPLING_INTERVAL_MIN` | int | `5` (pH), `30` (CO3) | Minutes between automatic measurements |
| `pumpTime_sec` | int | `60` | Seconds to flush sample before measuring |
| `mixTime` | int | `0` (pH), `10` (CO3) | Seconds to mix after dye injection |
| `waitTime` | int | `0` (pH), `5` (CO3) | Seconds to wait after stirrer stops |
| `Spectro_Integration_time` | float | `60.0` | Spectrometer integration time (ms) |
| `LIGHT_THRESHOLD_STS` | int | `15500` | Target intensity counts for STS spectrometer |
| `LIGHT_THRESHOLD_FLAME` | int | `60000` | Target intensity counts for FLAME spectrometer |
| `Autoadjust_state` | str | `"ON"` | `"ON"`, `"OFF"`, or `"ON_NORED"` |
| `drain_mode` | str | `"ON"` | Whether to drain cuvette after CO3 measurement |
| `drain_slot` | int | `19` | GPIO pin for drain relay |
| `air_slot` | int | `16` | GPIO pin for air pump relay (pushes liquid out) |
| `drain_time` | int | `15` | Seconds to run drain + air pump |
| `Ship_Code` | str | `"NB"` | Ship/platform identifier |

### `[pH]` section

| Key | Type | Example | Description |
|-----|------|---------|-------------|
| `LED_SLOTS` | list[int] | `[12, 13, 19, 16]` | GPIO BCM pins for LED PWM (Blue, Orange, Red, spare) |
| `LED1` | int | `55` | Blue LED PWM duty cycle (0–100) |
| `LED2` | int | `55` | Orange LED PWM duty cycle (0–100) |
| `LED3` | int | `55` | Red LED PWM duty cycle (0–100) |
| `Default_DYE` | str | `"MCP"` | Indicator dye: `"MCP"` or `"TB"` |
| `wl_NIR-` | int | `730` | NIR reference wavelength (nm) |
| `MCP_wl_HI` | int | `434` | MCP acid-form wavelength (nm) |
| `MCP_wl_I2` | int | `578` | MCP base-form wavelength (nm) |
| `TB_wl_HI` | int | `434` | TB acid-form wavelength (nm) |
| `TB_wl_I2` | int | `596` | TB base-form wavelength (nm) |
| `PPHOX_STRING_VERSION` | str | `"1"` | Data string protocol version |

### `[CO3]` section

| Key | Type | Example | Description |
|-----|------|---------|-------------|
| `WL_1` | int | `234` | First UV measurement wavelength (nm) |
| `WL_2` | int | `250` | Second UV measurement wavelength (nm) |
| `WL_3` | int | `350` | Reference UV wavelength (nm) |
| `LIGHT_SLOT` | int | `17` | GPIO pin for UV lamp relay |
| `SHUTTER_SLOT` | int | `27` | GPIO pin for shutter relay |
| `Default_DYE` | str | `"Pb_perchlor"` | `"Pb_perchlor"` or `"Pb_chlor"` |
| `lamp_time` | int | `3` | Minutes before measurement to pre-warm lamp |
| `PCO3_string_version` | str | `"1"` | Data string protocol version |

### `[TrisBuffer]` section (calibration)

| Key | Type | Example | Description |
|-----|------|---------|-------------|
| `S_tris_buffer` | int | `35` | Salinity of Tris calibration solution |
| `T_tris_buffer` | int | `20` | Temperature of calibration solution (°C) |
| `Calibration_threshold` | float | `0.005` | Max acceptable |ΔpH| between measured and theoretical |
| `Calibration_pump_time` | int | `30` | Seconds to pump calibration solution |

### `[QC]` section

| Key | Type | Example | Description |
|-----|------|---------|-------------|
| `flow_threshold` | int | `2000` | Min intensity difference (counts) confirming flow |

### Temperature probe calibration

Loaded from `configs/temperature_sensors_config.json`. Each entry keyed by `Probe_N`:
```json
{
  "Probe_1": {
    "is_calibrated": "True",
    "Calibr_coef": [-1.234, 15.678]
  },
  "Probe_Default": {
    "is_calibrated": "False",
    "Calibr_coef": [-1.0, 16.0]
  }
}
```
`T_cuvette = coef[0] * voltage + coef[1]` (result in °C)

---

## Hardware Interfaces

### Spectrometer (`Spectro_seabreeze` / `Spectro_localtest`)

Both implement the same interface:
```python
spectrometer.set_integration_time_not_async(time_ms: float)
await spectrometer.set_integration_time(time_ms: float)
spectrometer.get_wavelengths() -> np.ndarray        # pixel wavelength array (nm)
await spectrometer.get_intensities(num_avg=1, correct=True) -> np.ndarray
spectrometer.get_intensities_slow(num_avg=1, correct=True) -> np.ndarray  # sync
spectrometer.set_scans_average(num: int)            # not supported on FLAME
spectrometer.spectro_type: str                      # "STS" or "FLMT"
```

Spectro type detection: `seabreeze` returns a string representation; search for `"STS"` or `"FLMT"` substring. Default to `"FLMT"` if not found.

### GPIO / relays (via `pigpio`)

```python
rpi = pigpio.pi()

# SSR relay (simple on/off)
rpi.write(pin, True)   # turn on
rpi.write(pin, False)  # turn off

# PWM (LED control)
rpi.set_mode(pin, pigpio.OUTPUT)
rpi.set_PWM_frequency(pin, 100)        # 100 Hz
rpi.set_PWM_dutycycle(pin, duty)       # 0–255 (the code uses 0–100 scale via adjust_LED)
```

Note: `adjust_LED(led_index, duty_0_to_100)` calls `rpi.set_PWM_dutycycle(led_slots[led_index], duty_0_to_100)`.

### Bistable valve (`set_Valve`, `set_Valve_bistable`, `set_Valve_sync`)

```python
# VALVE_SLOTS = [enable_pin, ch1_pin, ch2_pin]
# Open:  write ch1=True, ch2=False, enable=True, sleep 0.3s, release all
# Close: write ch1=False, ch2=True (swapped), enable=True, sleep 0.3s, release all
```

Async version: `await set_Valve(True/False)` | Sync version: `set_Valve_sync(True/False)`

### ADC (temperature voltage)

```python
adc = ADCDifferentialPi(0x68, 0x69, 14)   # I2C, 14-bit
adc.set_pga(1)
voltage = adc.read_voltage(channel)        # returns float (volts)
```
`get_Voltage(nAver, channel)` averages `nAver` reads, returns rounded float.

### Dye pump (solenoid)

Each shot: relay on for 0.15 s, off for 0.35 s. `nshots` shots per injection event.

---

## Measurement Cycle (both instruments)

The full cycle is implemented as an async workflow. Steps in order:

```
1. [Optional] Pump sample — flush chamber for pumpTime_sec seconds
2. Close inlet valve
3. Auto-adjust light source (LEDs for pH, integration time for CO3)
4. Measure dark spectrum (LEDs off / shutter closed)
5. Measure blank spectrum (clean water, no dye)
6. For n_inj in range(ncycles):
   a. Start stirrer
   b. Inject dye: nshots pulses (0.15 s on / 0.35 s off per shot)
   c. Mix: sleep mixTime seconds
   d. Stop stirrer
   e. Wait: sleep waitTime seconds
   f. Read temperature voltage (ADC, 3 averages)
   g. Capture spectrum (specAvScans averages)
   h. Calculate absorbance
   i. Calculate pH or CO3
7. Compute final value (regression for pH, direct for CO3)
8. QC checks
9. [CO3 only, if drain_mode='ON'] Drain cuvette
10. Open inlet valve
11. Save results
```

---

## Absorbance Calculation (shared)

```python
absorbance_spectrum = -np.log10(
    (postinjection_spectrum - dark) / (blank - dark)
)
```
Absorbance at 3 wavelengths (`wvlPixels[0]`, `wvlPixels[1]`, `wvlPixels[2]`) are extracted.

Pixel indices: `find_nearest(wavelength_array, target_nm)` → `np.abs(array - value).argmin()`

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

With `ncycles = 1` (current default), `CO3` is taken directly from the single measurement row. The function `calc_final_co3(evalPar_df)` returns `(co3, T_cuvette)`.

### Light source (UV lamp)

- Relay-controlled; must warm up ~3 minutes before measurement
- Shutter (relay on `SHUTTER_SLOT`) blocks light during dark measurement
- Dark: close shutter → capture → open shutter
- Auto-adjust: integration time only (no lamp power control), same binary-search algorithm as pH but targets `wvlPixels` pixel levels

### Drain sequence

```python
turn_on_relay(drain_slot)
turn_on_relay(air_slot)
sleep(drain_time)   # seconds
turn_off_relay(air_slot)
turn_off_relay(drain_slot)
```

---

## Salinity Source

Priority order:
1. Manual input (used for single/manual measurements; not for continuous or calibration)
2. Calibration mode: always uses `TrisBuffer.S_tris_buffer` (= 35)
3. Continuous mode: `udp.FERRYBOX["salinity"]` (real-time from Ferrybox UDP)

---

## UDP Communication (`udp.py`)

Two background threads (start automatically on import):
- **Receiver** listens on port `56800` for `$PFBOX,...` datagrams from Ferrybox
- **Sender** broadcasts on port `56801` (or config `UDP_SEND`) `DATA_STRING` every 10 s

Parsed Ferrybox fields populated into `udp.FERRYBOX` dict:

| Key | Source message prefix |
|-----|-----------------------|
| `salinity` | `$PFBOX,SAL,` |
| `temperature` | `$PFBOX,TEMP,` |
| `pumping` | `$PFBOX,PUMP,` (int: 0=off, 1=on) |
| `latitude` | `$PFBOX,LAT,` |
| `longitude` | `$PFBOX,LON,` |
| `udp_ok` | True if last recv was within 1 s |

Data string formats (written to `udp.DATA_STRING`):
```
pH:  "$PPHOX,{version},{row_csv},*\n"
CO3: "$PCO3,{version},{row_csv},*\n"
```
where `row_csv` is the log row as CSV with no header.

Default `DATA_STRING = '$PHOX,-998'` until first measurement.

---

## Data Files and Formats

Base directory: `~/pHox_data/`

### SPT file (spectrum data)
Path: `data_pH/spt/{timestamp}.spt` or `data_co3/spt/{timestamp}.spt`  
Format: transposed CSV. Rows = measurement columns (`Wavelengths`, `dark`, `blank`, `0`, `1`, …). Columns = pixel indices. Written via `DataFrame.T.to_csv(path, index=True, header=False)`.

### EVL file (intermediate evaluation, per injection)

**pH EVL columns** (`data_pH/evl/{timestamp}.evl`):
```
pH, pK, e1, e2, e3, Voltage, salinity, A1, A2, T_cuvette, S_corr, Anir,
Vol_injected, TempProbe_id, Probe_iscalibr, TempCalCoef1, TempCalCoef2, DYE
```

**CO3 EVL columns** (`data_co3/evl/{timestamp}.evl`):
```
CO3, e1, e3e2, log_beta1_e2, Voltage, S, A1, A2, R, T_cuvette,
Vol_injected, S_corr, A350
```

### Log file (one row per final measurement)

**pH log** (`data_pH/pH.log`):
```
Time, Lon, Lat, fb_temp, fb_sal, SHIP, pH_cuvette, T_cuvette,
perturbation, evalAnir, pH_insitu, r_square, box_id
```

**CO3 log** (`data_co3/CO3.log`):
```
Time, Lon, Lat, fb_temp, fb_sal, SHIP, co3, box_id, T_cuvette
```

Calibration logs go to `data_pH_calibr/pH_cal.log` (same columns + `cal_result`, `difference`, `Buffer_theoretical_val`, `Buffer_temp`, `batch_number`).

### JSON upload (pH only)
Path: `data_pH/upload/{timestamp}.json`
```json
{
  "spt": { "<col_name>": [values...] },
  "eval": { "<col_name>": [values...] },
  "final_pH": { "<col_name>": scalar }
}
```

### Timestamp format
```python
datetime.now().strftime("%Y%m%d_%H%M%S")   # filename
datetime.now().isoformat("_")[0:16]          # in log rows
```

---

## Quality Control Checks (after each measurement)

Performed in order; results stored in `data_log_row`:

| QC flag | Column | Logic |
|---------|--------|-------|
| Flow | `flow_QC` | `(current_blue_pixel − last_injection_blue_pixel) > flow_threshold` |
| Dye | `dye_coming_qc` | `mean(blank − inj_0) > 5` counts |
| Biofouling | `biofouling_qc` | `specIntTime < 2000 ms` |
| Temp sensor | `temp_sens_qc` | Not all voltage readings identical |
| UDP | `UDP_conn_qc` | `udp.FERRYBOX['pumping'] is not None` |
| Overall | `overall_qc` | `all([flow, dye, bio, temp, udp])` |

QC is checked 3 seconds after the last measurement to allow valve to open.

---

## Output Precision (`precisions.PRECISION`)

```python
{"pH": 4, "pK": 4, "e1": 6, "e2": 6, "e3": 6, "Voltage": 5, "salinity": 2,
 "A1": 5, "A2": 5, "A3": 5, "vol_injected": 2, "T_cuvette": 3,
 "fb_temperature": 3, "evalAnir": 3, "perturbation": 3,
 "longitude": 6, "latitude": 6, "pCO2": 4}
```

---

## `Common_instrument` Constructor Requirements

`panelargs` must be an object with these boolean attributes:
- `localdev`: if True, use mock hardware classes and skip GPIO/ADC
- `co3`: if True, instantiate CO3 instrument (affects config loading and spectrometer type detection)

---

## Building a Standalone Module — Checklist

To implement a standalone (GUI-free) module for either instrument:

1. **Load config**: call `util.CONFIG_FILE` (already loaded at import; or reload from JSON path)
2. **Instantiate spectrometer**: `Spectro_seabreeze()` or `Spectro_localtest(panelargs)` for tests
3. **Instantiate instrument**: `pH_instrument(args)` or `CO3_instrument(args)`
4. **Initialise wavelengths**: call `instrument.calc_wavelengths()` → `instrument.get_wvlPixels(wvls)`
5. **Start UDP**: `import udp` (threads start automatically)
6. **Run measurement cycle** (async): implement the 11-step cycle from the Measurement Cycle section above, using instrument methods directly
7. **Save data**: build DataFrames matching the EVL and log column schemas above

The test/mock classes (`Test_pH_instrument`, `Test_CO3_instrument`) show the minimum interface any standalone replacement must implement.

---

## Key `Common_instrument` Methods

| Method | Description |
|--------|-------------|
| `load_config()` | Reads all operational config; populates all timing/hardware attributes |
| `update_temp_probe_coef()` | Reloads temperature calibration coefficients from JSON |
| `turn_on_relay(pin)` / `turn_off_relay(pin)` | GPIO write wrappers |
| `await set_Valve(bool)` | Open (True) / close (False) bistable valve (async) |
| `set_Valve_sync(bool)` | Synchronous valve operation |
| `await pumping(pumpTime)` | Run water pump + stirrer for pumpTime seconds |
| `await pump_dye(nshots)` | Fire dye solenoid nshots times |
| `get_Voltage(nAver, channel)` | Average ADC readings, return voltage |
| `calc_wavelengths()` | Return spectrometer wavelength array |
| `get_wvlPixels(wvls)` | Find pixel indices for `wvl_needed` wavelengths |
| `await get_sp_levels(pixel)` | Get intensity at a specific pixel index |
| `reset_lines()` | Set all GPIO output pins to 0 |

---

## References

- Clayton, T.D. & Byrne, R.H. (1993). Spectrophotometric seawater pH measurements. *Deep-Sea Research I*, 40(10), 2115–2129. (MCP dye)
- Liu, X., Patsavas, M.C., Byrne, R.H. (2011). Purification and characterization of meta-cresol purple for spectrophotometric seawater pH measurements. *Environ. Sci. Technol.*, 45(11), 4862–4868.
- Sharp, J.D. & Byrne, R.H. (2019). Carbonate ion concentrations in seawater: spectrophotometric determination. *Anal. Chim. Acta*, 1062, 45–56. (CO3 Sharp & Byrne 2019)
- Patsavas, M.C. et al. (2015). Spectrophotometric determination of carbonate ion in seawater. *Mar. Chem.*, 168, 80–89.
