---
description: "Use when implementing, extending, or reviewing the GUI for pH or CO3 seawater instruments. Covers layout structure, all views and tabs, plots, live data, manual controls, mode state machine, and API call mapping. Framework-agnostic (no PyQt). Do NOT use for instrument physics or hardware logic."
---

# GUI Design — pH and CO3 Instrument Panels

## Guiding Principles

- **Current implementation**: FastAPI + WebSocket backend (`gui/app.py`) + Vue 3 SPA frontend (`gui/static/index.html`). The frontend communicates exclusively via the WebSocket at `/ws` and the REST endpoint `GET /api/history`. The design intent below is described in terms of *what* to render, so a future frontend replacement can follow the same spec.
- **API-first**: the backend must interact with the instrument exclusively via the public API (`CO3InstrumentAPI` or `pHInstrumentAPI`). Hardware drivers are never imported by `app.py`.
- **Mode-driven**: every interactive widget has an enabled/disabled state determined by the current operating mode. The mode state machine is the single source of truth for what the user is allowed to do.
- **Async-safe**: measurement cycles and hardware calls are `async`. The backend must not block the event loop; all instrument API calls must be awaited within asyncio tasks.

## Deployment Context

The GUI is rendered in **Chromium kiosk mode** on a **Raspberry Pi 7" touchscreen (800 × 480 px)**. Design constraints:
- **Touch targets**: interactive elements must be at least 34–44 px tall. Tailwind `py-2.5` on `text-sm` buttons gives ~34 px; `py-3` gives ~38 px. Never use `py-1` on tappable elements.
- **No pinch-zoom**: the viewport has `user-scalable=no`. Layout must work at exactly 800 × 480 — do not rely on the user zooming in to read small text.
- **No keyboard**: prefer tap-friendly controls (buttons, selects) over free-text inputs wherever possible.

---

## Application-Level Shell

The shell is a full-screen (maximised) window with:
- **Title bar**: `"{box_id}, parameter CO3"` or `"{box_id}"` for pH, or `"{box_id}, parameters pH and pCO2"` when pCO2 is also active.
- **Close confirmation**: before the window actually closes, show a modal confirmation dialog ("Are you sure you want to exit?"). On confirm: turn off the light source (CO3 only), close the shutter (CO3 only), stop all periodic timers, call `api.disconnect()`, and stop UDP threads.

### Top-level layout

```
┌──────────────────────────────────────────────────────────────────────┐
│  PLOTS (left, ~40 % width)  │  TABS (right, ~60 % width)            │
│  ─────────────────────────  │  ─────────────────────────────────────│
│  Plot 1: Spectrum           │  [ Home ] [ Manual ] [ Config ]        │
│  Plot 2: Result             │  [ Status ] [ Log ]                    │
│                             │                                         │
│                             │  <active tab content>                  │
└──────────────────────────────────────────────────────────────────────┘
```

The plot panel and the tab panel are arranged side-by-side horizontally. The plots are fixed in view; only the tab content scrolls or changes.

---

## Plot Panel

### Plot 1 — "Light-source intensities"

**Purpose**: live view of the spectrometer output. Used for light-source alignment and monitoring during adjustment.

| Property | Value |
|----------|-------|
| X axis | Wavelength (nm) — full spectrometer range |
| Y axis | Intensity (counts), minimum 1 000, maximum ≈ `light_threshold * 1.05` |
| Grid | X and Y |
| Interaction | Zoom/pan disabled (read-only live view) |
| Update rate | Derived from integration time: `interval_ms = specIntTime + clamp(specIntTime * 2, 200, 1000)` |
| Live update | Active only when NOT in Measuring or Adjusting mode |

**Reference markers — pH instrument**:
- Horizontal dashed line at `light_threshold` counts (white)  — target intensity
- Vertical dashed lines at: HI wavelength (blue), I2 wavelength (orange), NIR wavelength (red)

**Reference markers — CO3 instrument**:
- X range restricted to 220–360 nm (UV range only)
- Vertical dashed lines at: λ1=234 nm (blue), λ2=250 nm (orange), λ3=350 nm (white)

**Data source**: `await api.get_spectrum()` — called on a periodic timer.  
During Measuring or Adjusting modes, **pause the periodic timer** (do not call `api.get_spectrum()`). After the cycle completes, update Plot 1 from `MeasurementResult.spectra.blank` (last clean spectrum before dye). Real-time spectrum updates mid-cycle require a future push-callback mechanism in the API.

---

### Plot 2 — Result plot

**pH instrument — "Last pH measurement"** (scatter + regression):

| Property | Value |
|----------|-------|
| X axis | Volume injected (mL) |
| Y axis | Temperature-corrected pH |
| Series 1 | All measured points (circles) — shows the raw scatter |
| Series 2 | Points used in the final regression (circles, highlighted in green) |
| Series 3 | Linear regression line through Series 2 |
| Interaction | Zoom/pan disabled |

Populated after each complete measurement cycle using the `evalPar_df` DataFrame.

**CO3 instrument — "Last CO3 measurement"** (absorbance spectra):

| Property | Value |
|----------|-------|
| X range | 220–360 nm |
| Y axis | Absorbance (A.U.) |
| Series | One line per injection cycle (up to `n_cycles` coloured lines) |
| Colours | Cycle through: red, green, blue, magenta, yellow |
| Interaction | Zoom/pan disabled |

Before each new measurement cycle, all lines are reset to zero. After the cycle completes, draw all injection lines from `MeasurementResult.spectra.injections` (a `dict[int, np.ndarray]` keyed by 0-based injection index). Real-time per-injection updates during the cycle require a future push-callback in the API.

---

## Tab: Home

Primary control tab. Contains: measurement buttons, progress tracker, last-result table, and live sensor readouts.

### Measurement buttons (top row)

| Button | Type | Label | Behaviour |
|--------|------|-------|-----------|
| Continuous | Toggle | "Continuous measurements" | Start/stop automatic sampling at the configured interval |
| Single | Toggle | "Single measurement" | Run one complete measurement cycle on demand |

- While either button is active (pressed), the other is disabled.
- A **filename dialog** is shown before a single measurement — the user can override the auto-generated timestamp name.
- Before a single measurement, show a **confirmation dialog**: "Did you pump to flush the sampling chamber?"

### Measuring progress tracker (group box "Measuring Progress")

A vertical list of read-only checkboxes, one per step, checked by the cycle as it advances:
1. Adjusting Light
2. Dark and blank
3. Measurement 1
4. Measurement 2  *(if n_cycles > 1)*
5. …  *(up to n_cycles)*

All checkboxes are read-only (display only). They are all unchecked at the start of a cycle and reset to unchecked when the cycle ends.

### Last measurement table (group box "Last Measurement")

A 2-column, read-only table. Left column = label, right column = value.

**pH instrument rows**:
| Row | Label | Source field |
|-----|-------|-------------|
| 0 | pH cuvette | `pH_cuvette` |
| 1 | T cuvette | `T_cuvette` |
| 2 | pH insitu | `pH_insitu` |
| 3 | T insitu | `fb_temp` |
| 4 | S insitu | `fb_sal` |

**CO3 instrument rows**:
| Row | Label | Source field |
|-----|-------|-------------|
| 0 | CO3 | `co3` |
| 1 | T insitu | `fb_temp` |
| 2 | S insitu | `fb_sal` |
| 3 | T cuvette | `T_cuvette` |

### Live sensor updates (group box "Live Updates")

Read-only numeric fields updated every 500 ms by a background timer:

| Label | Value | Source |
|-------|-------|--------|
| T insitu | °C | Ferrybox UDP `temperature` |
| S insitu | PSU | Ferrybox UDP `salinity` |
| T cuvette | °C | `api.get_temperature()` |
| Voltage | V | raw ADC voltage |

Also shown: **Ferrybox pump status** indicator (read-only checkbox/indicator, "Ferrybox pump is on") — reflects `udp.FERRYBOX["pumping"]`.

### Status message box

A read-only multi-line text area below the live sensor group. Displays human-readable progress messages:
- "Next sample in N minutes"
- "Ongoing measurement"
- "Autoadjusting LEDS"
- "The measurement is finished"
- "Was not able to do the measurement, the cuvette is dirty"
- "Continuous mode paused"

---

## Tab: Manual

Allows direct hardware control. Only available when Manual mode is active (toggle button).

### Manual mode toggle button

A prominent toggle button at the top: "Manual Control". Enabling it activates all manual widgets. Disabling it de-activates them.

**Auto-disable rule**: if Continuous mode is active and the next sample is ≤ 4 minutes away, the Manual toggle is automatically disabled.

### Hardware buttons group (group box "Manual Control")

All buttons are **toggles** (on/off) except where noted. All disabled by default; enabled only in Manual mode.

**Shared — both instruments**:

| Button | Action (on) | Action (off) | API call |
|--------|------------|-------------|---------|
| Dye pump | Inject 3 dye shots | — (auto-off) | `await api.pulse_dye_pump(3)` |
| Water pump | Run pump | Stop pump | `await api.run_water_pump(...)` |
| Adjust Light | Run auto-adjust | — (auto-off) | `await api.auto_adjust_integration_time()` |
| Light | Turn on light/LEDs | Turn off | `api.turn_on_light()` / `api.turn_off_light()` |
| Inlet valve | Open valve | Close valve | `await api.open_valve()` / `await api.close_valve()` |
| Stirrer | Start stirrer | Stop stirrer | `api.start_stirrer()` / `api.stop_stirrer()` |

**CO3 only, additional buttons**:

| Button | Action (on) | Action (off) | API call |
|--------|------------|-------------|---------|
| Drain | Run drain sequence | Stop drain | `await api.drain_cuvette()` |
| Shutter | Open shutter | Close shutter | `api.open_shutter()` / `api.close_shutter()` |

**Dye pump behaviour**: clicking fires 3 shots, then the button automatically resets to off. After pumping, capture and display a fresh spectrum in Plot 1.

**Drain behaviour**: closing the drain first requires the inlet valve to be closed; if it is open, close it first, then drain, then re-open the valve.

### LED control group (group box "LED values") — pH only

Three rows, one per LED (Blue, Orange, Red):

| Control | Type | Range | Behaviour |
|---------|------|-------|-----------|
| Slider | Horizontal, 0–100 | Integer | Immediate LED PWM update via `api` |
| Spin box | Integer, 0–100 | Integer | Linked bidirectionally with slider |
| `+` button | Push | — | Increment by 1 |
| `−` button | Push | — | Decrement by 1 |

All three controls are linked: changing one updates the others. Changing any of them calls the instrument to update the LED duty cycle immediately. The Light toggle button is automatically set to ON when a slider or spinbox changes.

> **CO3 instrument**: this LED control group is present in the layout (for visual consistency) but all controls are disabled — CO3 uses a UV lamp controlled only by the Light toggle, not individual LED PWM.

---

## Tab: Config

Run-time parameter changes (saved to the config file on demand).

### Action buttons (top row)

| Button | Behaviour |
|--------|-----------|
| Save config | Persist current combo-box selections to the JSON config file |
| Test UDP | Toggle: start/stop broadcasting a test data string every 10 s |

All config widgets are **disabled** during Measuring, Adjusting, and Calibration modes.

### Configuration table

A 2-column table (label | editor). Read-only editing triggers disabled.

| Row | Label | Widget type | Values | Notes |
|-----|-------|-------------|--------|-------|
| 0 | DYE type | Dropdown | pH: ["TB", "MCP"] / CO3: ["Pb_perchlor"] | Changing pH dye updates wavelength selections |
| 1 | Autoadjust state | Dropdown | ["ON", "OFF", "ON_NORED"] | ON_NORED skips Red LED |
| 2 | Pumping time (seconds) | Read-only label | — | From config, display only |
| 3 | Sampling interval (min) | Dropdown | [5, 7, 10, 15, 20, 30, 60] | Affects continuous mode timer |
| 4 | Spectro integration time | Dropdown | 1–19 (step 1), 20–90 (step 10), 100–4900 (step 100) ms | Changes live spectrometer setting immediately |
| 5 | Ship | Dropdown | Valid ship codes from config | |
| 6 | Temp probe id | Dropdown | Probe_1 … Probe_24 | Reloads calibration coefficients on change |
| 7 | Temp probe is calibrated | Read-only checkbox | — | Display only; from temp probe config |
| 8 | Drain mode | Dropdown | ["ON", "OFF"] | CO3 only (visually hidden for pH) |

**Scroll-wheel on dropdowns must be suppressed** to prevent accidental changes during normal operation.

### Salinity source

There is **no manual-salinity widget** (the original's manual-salinity picker was removed).
The instrument always reads salinity through the `IFerryboxClient`:
- Single / Continuous mode → latest Ferrybox salinity (`api.get_ferrybox_data().salinity`).
  When `ferrybox.enabled: false`, `StaticFerryboxClient` supplies a fixed fallback salinity.
- Calibration mode → always uses the Tris-buffer salinity (`tris_buffer.salinity`, 35 PSU).

Because of this, `run_single_measurement()` and the continuous loop take **no** salinity
argument — the API resolves salinity internally.

---

## Tab: Status

Monitoring and QC. No interactive controls (read-only).

### Dye level indicator (group box "Dye Level")

A horizontal progress bar, range 0–2 000 (arbitrary "1 000 = one dye bag" units).

Buttons beside it:
- **"1 bag Refilled"** — adds 1 000 if level < 1 000, or sets to 2 000 if 1 000 ≤ level < 2 000
- **"Clear all"** — resets to 0

The current value is persisted to the config JSON file on every change.  
Each completed measurement cycle automatically deducts: `n_cycles × dye_volume_per_shot_ml × dye_n_shots` (from config).

### Last measurement QC (group box "Last Measurement Quality Control")

Four tristate checkboxes (not user-editable):

| Checkbox | Label | Pass condition |
|----------|-------|----------------|
| Flow | Flow | Blue pixel after measurement > blue pixel at last injection + `flow_threshold` |
| Dye | Dye | Mean(blank − injection_0) > 5 counts |
| Biofouling | Biofouling | `specIntTime < 2000 ms` |
| Temp sensor | Temp sensor | Not all voltage readings are identical (probe is alive) |

State encoding:
- **Unchecked** = not yet evaluated (grey)
- **Partially checked** = FAIL (red / warning colour)
- **Checked** = PASS (green)

### Calibration result group (group box "Calibration") — pH only

| Widget | Description |
|--------|-------------|
| "Make calibration check" toggle button | Starts the calibration workflow |
| Tristate result checkbox (read-only) | 0 = no result, 1 = failed, 2 = passed |
| Date label | Date of last calibration check |

---

## Backend Architecture (`gui/app.py`)

The backend is a FastAPI application running under uvicorn. It owns the instrument API instance and all background tasks. All frontend communication is via WebSocket (push-based), with one REST endpoint for initial history load.

### REST Endpoints

| Method | Path | Response | Description |
|--------|------|----------|-------------|
| `GET` | `/` | `FileResponse` | Serve Vue 3 SPA (`gui/static/index.html`) |
| `GET` | `/api/history` | `list[dict]` | Last 50 rows from `CO3.log` or `pH.log`; each dict has `timestamp`, `t_cuvette`, `value` (CO3 or pH_cuvette), and `pH_insitu` (pH only) |

### WebSocket — `/ws`

**On connect:** server immediately broadcasts a `state_snapshot` message followed by a `history` message to the new client.

**On receive:** parse JSON and dispatch the `cmd` field via `InstrumentState.handle_command()`.

#### Outgoing message types (server → client)

| `type` | Key fields | When sent |
|--------|-----------|----------|
| `state_snapshot` | `instrument_type`, `modes`, `measurement_n`, `last_result`, `wavelengths`, `n_cycles`, `interval_s` | On every new WebSocket connection |
| `history` | `points: list[dict]` | On every new WebSocket connection. Not consumed by Plot 2 (which renders the **last measurement** only — pH scatter+regression / CO3 absorbance). Available for an optional time-series view |
| `sensor_update` | `t_cuvette`, `voltage`, `fb_temp`, `fb_sal`, `fb_pumping` | Every 500 ms by `_sensor_poll`; `fb_pumping` drives the Ferrybox-pump indicator and Paused mode |
| `spectrum_update` | `intensities: list[float]` | Every ~int_time + 200–1000 ms by `_spectrum_poll`; paused during Measuring/Adjusting |
| `step_complete` | `step: str` | When `on_step` callback fires during a measurement cycle |
| `measurement_result` | `instrument: "co3"\|"ph"`, plus all result fields. **CO3** also includes `absorption_wavelengths: list[float]` (220–360 nm) and `absorption_spectra: dict[str, list[float]]` (absorbance per injection, keyed by 0-based string index). **pH** also includes `slope` and `injections_scatter: list[{vol_ml, pH}]` (drives the Plot 2 scatter + regression line) | After a successful measurement cycle |
| `countdown` | `seconds_remaining: int` | Every 15 s while Continuous mode is active |
| `mode_change` | `modes: list[str]`, `measurement_n: int` | When the mode set changes |
| `dye_level` | `value: int` | When the dye level changes (refill, clear, or auto-deduction after a cycle) |
| `qc_update` | `qc_flow`, `qc_dye`, `qc_biofouling`, `qc_temp_sensor`, `qc_udp`, `qc_overall` (each `bool \| null`) | After a measurement cycle's QC is evaluated |
| `calibration_update` | `steps: list[dict]` (per-step progress + tri-state result), `result`, `date` | During and after the pH calibration workflow |
| `log_line` | `text: str` | When a Python `logging` record is emitted |

#### Incoming commands (client → server)

| `cmd` | Extra fields | Backend action |
|-------|-------------|---------------|
| `start_continuous` | — | Start `_continuous_loop()` as asyncio task (salinity read from Ferrybox) |
| `stop_continuous` | — | Set `_stop_continuous` event |
| `start_single` | — | Run `_run_measurement(flush_before=False)` once (salinity read from Ferrybox) |
| `open_valve` | — | `await api.open_valve()` |
| `close_valve` | — | `await api.close_valve()` |
| `turn_on_light` | — | `api.turn_on_light()` (CO3 only) |
| `turn_off_light` | — | `api.turn_off_light()` (CO3 only) |
| `open_shutter` | — | `api.open_shutter()` (CO3 only) |
| `close_shutter` | — | `api.close_shutter()` (CO3 only) |
| `start_stirrer` | — | `api.start_stirrer()` |
| `stop_stirrer` | — | `api.stop_stirrer()` |
| `run_water_pump` | `duration_s: float` | `await api.run_water_pump(duration_s)` |
| `pulse_dye_pump` | `n_shots: int` | `await api.pulse_dye_pump(n_shots)` |
| `drain_cuvette` | — | `await api.drain_cuvette()` |
| `auto_adjust` | — | `await api.auto_adjust_integration_time()` with mode lock |
| `turn_on_leds` | — | `api.turn_on_leds()` (pH only) |
| `turn_off_leds` | — | `api.turn_off_leds()` (pH only) |
| `set_led_duty_cycle` | `channel: int`, `duty: int` | `api.set_led_duty_cycle(channel, duty)` (pH only); auto-sets the Light toggle to on |
| `refill_dye` | — | Add one bag to the dye level (+1000, capped at 2000) and persist to config |
| `clear_dye` | — | Reset dye level to 0 and persist to config |
| `start_calibration` | `batch_number: int`, `with_cleaning: bool` | Start the pH Tris-buffer calibration workflow as an asyncio task (pH only) |
| `stop_calibration` | — | Abort the running calibration workflow |
| `test_udp` | `enabled: bool` | Toggle the periodic test-UDP broadcast (every 10 s) |
| `save_config` | — | Persist current config selections to the YAML config file |
| `set_dye_type` | `dye: str` | Update `co3.dye` / `ph.dye` (pH dye change also updates wavelengths) |
| `set_autoadjust` | `mode: str` | Set autoadjust mode `ON`/`OFF`/`ON_NORED` |
| `set_sampling_interval` | `minutes: int` | Update continuous-mode interval |
| `set_integration_time` | `time_ms: float` | Set spectrometer integration time immediately |
| `set_drain_mode` | `mode: str` | Set drain mode `ON`/`OFF` (CO3 only) |

### Background Tasks

`InstrumentState` runs three perpetual asyncio tasks while the server is alive:

| Task | Period | Description |
|------|--------|-------------|
| `_sensor_poll()` | 500 ms | Reads `api.get_temperature()`, `api.get_voltage()`, `api.get_ferrybox_data()`; broadcasts `sensor_update` |
| `_spectrum_poll()` | `specIntTime + clamp(specIntTime×2, 200, 1000)` ms | Calls `api.get_spectrum()` and broadcasts `spectrum_update`; **paused** (skipped) while `"Measuring"` or `"Adjusting"` in mode set |
| `_countdown_loop()` | 15 s | Broadcasts `countdown` message with seconds until next measurement; only active while `"Continuous"` in mode set |

### Mode Set

The backend mode set is the **single source of truth** for the GUI's enable/disable rules and
is broadcast on every change via `mode_change`. Modes are tracked as a Python `set[str]`;
multiple modes can be active simultaneously (e.g. `{"Continuous", "Measuring"}` during a
continuous cycle run).

| Mode string | Meaning |
|------------|--------|
| `"Measuring"` | A measurement cycle is actively running |
| `"Adjusting"` | Auto-adjustment of light/LEDs is running |
| `"Continuous"` | Automatic periodic sampling is scheduled |
| `"Manual"` | Manual hardware control is enabled by the user |
| `"Calibration"` | A pH calibration check cycle is running |
| `"Paused"` | Continuous mode is active but paused because the Ferrybox pump is off (`fb_pumping == 0`); resumes automatically when `fb_pumping` returns to `1` |

Every mode change broadcasts a `mode_change` message to all clients.

---


The GUI has a set of **major modes** that can be active simultaneously. The mode determines which widgets are enabled or disabled.

### Modes

| Mode | Meaning |
|------|---------|
| `Measuring` | A measurement cycle is actively running |
| `Adjusting` | Auto-adjustment of light/LEDs is running |
| `Manual` | User has enabled manual hardware control |
| `Continuous` | Automatic periodic sampling is scheduled |
| `Calibration` | A calibration check cycle is running |
| `Paused` | Continuous mode is active but temporarily paused (Ferrybox pump off) |
| `Flowcheck` | Flow check routine is running |

Modes are a **set** (multiple can be active); e.g. `{Continuous, Measuring}` is valid.

### Widget enable/disable rules

| Widget / group | Enabled when |
|----------------|-------------|
| Single measurement button | No active `Measuring`, `Calibration`, or `Continuous` |
| Continuous button | No active `Measuring` or `Calibration` |
| Calibration button (pH) | No active `Measuring`, `Continuous`, or `Calibration` |
| Manual mode toggle | No active `Measuring`, `Adjusting`, or `Calibration`; and if Continuous is active, only when `time_until_next ≥ 4 min` |
| All manual hardware buttons | `Manual` is active |
| LED sliders/spinboxes (pH) | `Manual` is active |
| All config widgets | No active `Measuring`, `Adjusting`, or `Calibration` |

### Continuous mode timing display

While Continuous mode is active, a countdown is shown in the status box: "Next sample in N minutes". The countdown decrements every 15 seconds.

**Paused state**: when the Ferrybox pump status (`udp.FERRYBOX["pumping"]`) changes to 0 (pump off), Continuous mode is paused — the timer is stopped, the Manual toggle is disabled, and a "Continuous mode paused" message is shown. When `pumping` returns to 1, the mode resumes automatically.

---

## CO3-Specific GUI Behaviour

### Lamp warm-up

The CO3 UV lamp requires ~3 minutes to stabilise before a measurement.

- In Continuous mode: when `time_until_next_sample ≤ lamp_time` (from config, default 3 min), **automatically** turn on the light and open the shutter.
- For a single measurement where the light is off: show a status message "Wait for the lamp warming" and wait 3 minutes before proceeding.
- On measurement completion (or Continuous mode exit): turn off the light and close the shutter.

### Drain workflow

After each CO3 measurement cycle (if `measurement.drain_after = true` in config):
1. Show "Draining" in the status box
2. Call `await api.drain_cuvette()`
3. The Drain button reflects the running state (checked while draining)

---

## pH-Specific GUI Behaviour

### Calibration check workflow

Triggered from the Status tab "Make calibration check" button. Runs as follows:

**Step 1: Batch number dialog**
- Modal dialog with an integer input for the calibration solution batch number.
- Buttons: `+1`, `−1`, `+10`, `−10`, OK, Cancel.

**Step 2: Valve instruction dialogs**
Three sequential instruction dialogs (OK / Cancel):
1. Prompt to turn physical valves to calibration position and place tube in Tris buffer bottle
2. Prompt to close the drain valve once cuvette is empty
3. Yes/No: "Do you want calibration check to include cuvette cleaning?"

**Step 3: Calibration progress dialog**
A non-blocking progress window showing:
- Group "Before Cuvette cleaning": 3 measurement steps with progress checkbox + tristate result per step
- Group "After Cuvette cleaning" (if user chose yes): 3 more measurement steps
- A "Stop Calibration" button to abort at any time

**Step 4: Measurement cycles (×3 before, ×3 after)**

For each calibration step:
1. Run water pump for `pumpTime_s` (first step) or `calibration_pump_time` (subsequent steps)
2. Run one complete `sample_cycle`
3. Compare measured pH against the theoretical Tris buffer pH (`calc_pH_buffer_theo`)
4. Mark step checkbox as ✓ (green) if `|ΔpH| < calibration_threshold` (0.005), or ✗ (red) if not

If the cuvette is too dirty to auto-adjust, show a warning dialog and skip remaining steps.

**Step 5: Cuvette cleaning dialog** (between before-group and after-group)
- A modal dialog with a live spectrum plot (manually refreshed on button click), instructing the user to clean the cuvette.
- OK → continue to after-cleaning steps; Cancel → abort

**Step 6: Results and close**
After all steps complete:
- Show final valve-return instruction dialogs ("Turn valves back to Ferrybox mode", then an emphatic confirmation dialog)
- Update the calibration result checkbox: green (pass) if majority of last 3 steps passed, red (fail) otherwise
- Record the date

### LED auto-adjustment logic for GUI

After auto-adjustment completes:
1. Update all three slider/spinbox values from the new LED values
2. Update the spectrometer integration time dropdown
3. Save the new LED values and integration time back to the config file
4. Capture and display a fresh spectrum in Plot 1

---

## Autostart Behaviour

On startup, if `AUTOSTART = "True"` in config:

| Mode | Behaviour |
|------|-----------|
| `"pump"` | Wait for Ferrybox pump to be on (poll every 1 s), then start Continuous mode. Continue polling every 10 s and pause/resume automatically. |
| `"time"` | Wait until a scheduled time, then start Continuous mode. |
| `"now"` | Start Continuous mode immediately. |

On autostart, also:
- Open the inlet valve
- Turn on LEDs (pH) or pre-warm lamp based on `lamp_time` (CO3)
- Start the live spectrum plot timer
- Start the sensor info timer (every 500 ms)
- Send an initial data string to Ferrybox (with placeholder values −998)

---

## API Call Mapping Reference

| GUI action | API call |
|-----------|---------|
| Start single measurement | `await api.run_single_measurement(flush_before, on_step)` (salinity resolved internally) |
| Get live spectrum | `await api.get_spectrum()` |
| Read temperature | `api.get_temperature()` |
| Open/close valve | `await api.open_valve()` / `await api.close_valve()` |
| Turn light on/off | `api.turn_on_light()` / `api.turn_off_light()` |
| Open/close shutter | `api.open_shutter()` / `api.close_shutter()` |
| Run water pump | `await api.run_water_pump(duration_s)` |
| Inject dye | `await api.pulse_dye_pump(n_shots)` |
| Stirrer on/off | `api.start_stirrer()` / `api.stop_stirrer()` |
| Drain cuvette | `await api.drain_cuvette(duration_s)` |
| Auto-adjust | `await api.auto_adjust_integration_time()` |
| Connect/disconnect | `await api.connect()` / `await api.disconnect()` |
| Get wavelengths | `api.wavelengths` (property, after connect) |

The GUI must **never** import or call hardware drivers (`pigpio`, `seabreeze`, `ADCDifferentialPi`) directly.

---

## Update Rates

| Update | Period | Notes |
|--------|--------|-------|
| Live spectrum plot | `specIntTime + clamp(specIntTime×2, 200, 1000)` ms | Paused during Measuring/Adjusting |
| Sensor info (T, S, voltage) | 500 ms | Always active after autostart |
| Continuous-mode countdown | 15 000 ms (15 s) | Only when Continuous is active |
| Continuous-mode measurement trigger | `samplingInterval` minutes | Only when Continuous is active |
| Spectrum update during cycle | Manual push (each spectrometer read) | Via a secondary no-request update |

---

## Instrument Differences Summary

| Feature | pH instrument | CO3 instrument |
|---------|--------------|----------------|
| Light source control | 3 LED PWM sliders (Blue/Orange/Red) | Single UV lamp toggle |
| Shutter button | Not shown | Shown in Manual tab |
| Drain button | Not shown | Shown in Manual tab |
| Plot 2 | Scatter + regression (pH vs vol. injected) | Absorbance spectra (UV range) per injection |
| Calibration workflow | Full Tris buffer calibration | Not implemented (log only) |
| Lamp warm-up | N/A | 3 min before measurement |
| Autoadjust target | Individual LED PWM duty cycles | Spectrometer integration time only |
| Last measurement table | pH cuvette, T cuvette, pH insitu, T insitu, S insitu | CO3, T insitu, S insitu, T cuvette |
| Config drain mode row | Hidden | Shown |
| Autostart: light | Turn on LEDs | Pre-warm lamp based on countdown |

---

## Data String Sent to Ferrybox

After each successful (non-calibration) measurement, the GUI constructs and broadcasts:

**pH**: `$PPHOX,{version},{row_csv},*\n`

CSV columns in order: `Time, Lon, Lat, fb_temp, fb_sal, SHIP, pH_cuvette, T_cuvette, perturbation, evalAnir, pH_insitu, r_square, box_id`

**CO3**: `$PCO3,{version},{row_csv},*\n`

CSV columns in order: `Time, Lon, Lat, fb_temp, fb_sal, SHIP, co3, box_id, T_cuvette`

Broadcast every 10 s via UDP port `UDP_SEND` (56801 for pH, configurable). An initial "empty" string with placeholder values −998 is broadcast on startup.
