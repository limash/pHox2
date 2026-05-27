# phox2 — Seawater Spectrophotometric Instrument

A modular Python package for autonomous **pH and CO₃²⁻ (carbonate)** seawater measurement using spectrophotometry. Supports both mock hardware (for development/testing) and real hardware deployment on Raspberry Pi.

## Overview

phox2 runs two instrument types from the same codebase, selected by config file:

| Instrument | Measures | Dye | Wavelengths |
|------------|----------|-----|-------------|
| **CO₃** | Carbonate ion (µmol/kg) | Pb(ClO₄)₂ or Pb(Cl)₂ | 234, 250, 350 nm (UV) |
| **pH** | Seawater pH (total scale) | MCP or TB | 434, 578/596, 730 nm (VIS) |

Both instruments share the same fluidic hardware (pumps, bistable valve, stirrer, drain, temperature ADC, USB spectrometer). The CO₃ instrument adds a UV lamp + mechanical shutter; the pH instrument replaces these with a PWM-controlled LED array.

The package handles:

- **Hardware control**: pumps, valves, spectrometer, ADC, temperature probes, LED array, and relays
- **Measurement cycles**: automated sample preparation, dye injection, equilibration, and optical measurement
- **Data acquisition**: spectral data, temperature measurements, and quality control
- **Ferrybox integration**: optional UDP communication for salinity/temperature from a ship Ferrybox system
- **Configuration management**: hardware pins, calibration coefficients, and measurement parameters via Hydra/OmegaConf

## Quick Start

### Regular System (Mock Hardware)

Perfect for development, testing, and non-hardware environments.

#### Prerequisites

- Python 3.11 or later
- `uv` package manager (recommended) or `pip`

#### Installation

```bash
# Clone/navigate to the repository
cd /path/to/phox2

# Install in development mode
uv sync

# Or with pip:
pip install -e .
```

#### Run a Single Measurement

A `--config-name` is always required to select the instrument type:

```bash
# CO3 instrument — mock hardware:
uv run scripts/run_single_measurement.py --config-name co3_config

# pH instrument — mock hardware:
uv run scripts/run_single_measurement.py --config-name ph_config
```

The measurement will:
1. Perform a simulated measurement cycle (accelerated 100× by default in mock mode)
2. Write a Hydra config snapshot to `outputs/<date>/<time>/`
3. Save spectral data, per-injection values, and a summary log to `~/phox_data/data_co3/` or `~/phox_data/data_ph/`

#### Run Continuously

```bash
# CO3, 5-minute interval (default):
uv run scripts/run_continuous_measurement.py --config-name co3_config

# pH, custom 2-minute interval:
uv run scripts/run_continuous_measurement.py --config-name ph_config continuous.interval_s=120

# Stop safely with Ctrl-C — current measurement finishes before exit.
```

#### Run the GUI

Install the GUI extras and launch the web interface:

```bash
uv sync --extra gui

# CO3 instrument (mock hardware):
uv run scripts/run_gui.py --config-name co3_config

# pH instrument (mock hardware):
uv run scripts/run_gui.py --config-name ph_config
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.

#### Common Overrides

Any config key can be overridden on the command line:

```bash
# Pass salinity manually (if not reading from Ferrybox):
uv run scripts/run_single_measurement.py --config-name co3_config measurement.salinity=34.5

# Skip drain cycle (useful during bench testing):
uv run scripts/run_single_measurement.py --config-name co3_config measurement.drain_after=false

# Run at real speed (time_acceleration=1) instead of 100×:
uv run scripts/run_single_measurement.py --config-name co3_config measurement.time_acceleration=1
```

---

## Raspberry Pi Deployment

Instructions for installing and running on real hardware with a Raspberry Pi.

### Prerequisites

**Hardware:**
- Raspberry Pi 4 or later (4 GB+ RAM recommended)
- Freshly imaged Raspberry Pi OS (Bookworm or later)
- Instrument hardware connected to GPIO pins and I²C bus

**Software:**
- Python 3.11 or later

### Installation on Raspberry Pi

#### 1. Update System

```bash
sudo apt update
sudo apt upgrade -y
```

#### 2. Install System Packages

Install everything possible via apt — prebuilt system packages are faster and avoid
compiling C extensions from source:

```bash
sudo apt install -y \
  build-essential python3-dev python3-venv \
  python3-lgpio \
  python3-smbus i2c-tools \
  libusb-1.0-0 libusb-1.0-0-dev libusb-dev pkg-config
```

| Package | Purpose |
|---------|---------|
| `build-essential python3-dev` | C compiler for building seabreeze |
| `python3-lgpio` | GPIO/PWM driver — prebuilt, avoids compiling lgpio from source |
| `python3-smbus` | I²C driver for the ADC board |
| `i2c-tools` | `i2cdetect` diagnostic utility |
| `libusb-1.0-0-dev` | Modern libusb headers (seabreeze C library) |
| `libusb-dev` | Legacy libusb 0.x headers (`usb.h`, also required by seabreeze) |
| `pkg-config` | Used by seabreeze's build system to locate libusb |

seabreeze's build system looks for a pkg-config package named `libusb`, but Debian names
it `libusb-1.0`. Create an alias:

```bash
PKGDIR=$(pkg-config --variable=pcfiledir libusb-1.0)
sudo ln -sf "$PKGDIR/libusb-1.0.pc" "$PKGDIR/libusb.pc"
```

Allow the current user to access GPIO without sudo:

```bash
sudo usermod -a -G gpio $USER
# Log out and back in for group changes to take effect
```

#### 3. Configure I²C

Enable I²C interface:

```bash
sudo raspi-config nonint do_i2c 0  # Enable I²C
```

Verify I²C devices are visible:

```bash
i2cdetect -y 1
```

#### 4. Clone and Install the Package

Create the venv with `--system-site-packages` so that the system-installed `python3-lgpio`
and `python3-smbus` are visible inside it — pip then only needs to build `seabreeze` and
install the pure-Python packages:

```bash
# Clone or navigate to the repository
cd /path/to/phox2

# Create and activate a virtual environment
python3 -m venv --system-site-packages .venv
source .venv/bin/activate

# Install with real hardware and GUI dependencies
pip install -e ".[hardware,gui]"
```

#### 5. Update Configuration

Edit `configs/co3_config.yaml` or `configs/ph_config.yaml` to match your hardware:

```yaml
hardware:
  use_mock: false          # use real hardware

gpio:
  # BCM pin numbers — verify against your physical wiring
  valve_enable_pin: 24
  valve_ch1_pin: 23
  valve_ch2_pin: 25
  water_pump_pin: 21
  dye_pump_pin: 19
  stirrer_pin: 20
  drain_pin: 16
  air_pin: 26
  # CO3 only:
  light_pin: 17            # UV lamp relay
  shutter_pin: 27          # mechanical shutter relay
  # pH only (instead of light/shutter):
  # ph.led_slots: [12, 13, 19, 16]   # PWM pins for LED array

adc:
  temperature_channel: 8   # ADCDifferentialPi channel for temperature probe

spectrometer:
  integration_time_ms: 18.0

measurement:
  time_acceleration: 1     # set to 1 for real hardware (not accelerated)
```

#### 6. Test Hardware Communication

Before running measurements, verify hardware is accessible:

```bash
# Check GPIO is accessible via lgpio
python3 -c "import lgpio; h = lgpio.gpiochip_open(0); print('GPIO OK'); lgpio.gpiochip_close(h)"

# Check I²C devices are visible
i2cdetect -y 1

# Check USB spectrometer connection
lsusb | grep -i "ocean"
```

### Run a Measurement on Raspberry Pi

```bash
# Activate the virtual environment first (if not already active)
source .venv/bin/activate

# Single CO3 measurement with real hardware:
python scripts/run_single_measurement.py --config-name co3_config hardware.use_mock=false

# Single pH measurement:
python scripts/run_single_measurement.py --config-name ph_config hardware.use_mock=false

# With manual salinity override:
python scripts/run_single_measurement.py --config-name co3_config hardware.use_mock=false measurement.salinity=34.5
```

### Run the GUI on Raspberry Pi

Launch the web interface with real hardware:

```bash
# Activate the virtual environment first (if not already active)
source .venv/bin/activate

# CO3 instrument:
python scripts/run_gui.py --config-name co3_config hardware.use_mock=false

# pH instrument:
python scripts/run_gui.py --config-name ph_config hardware.use_mock=false
```

The server listens on port 8000. Access it:
- Locally on the Pi: [http://localhost:8000](http://localhost:8000)
- From another machine on the same network: `http://<raspberry-pi-ip>:8000`

To find the Pi's IP address:

```bash
hostname -I
```

To keep the GUI running after you disconnect from SSH, use `tmux` or `screen`:

```bash
tmux new -s phox2
source .venv/bin/activate
python scripts/run_gui.py --config-name co3_config hardware.use_mock=false
# Detach with Ctrl+B, D
```

### Autostart on Boot (systemd)

The recommended approach for unattended deployment is a systemd service that launches the GUI with continuous measurements enabled automatically. The service restarts on failure and routes all output to the system journal.

#### 1. Ensure required group memberships

```bash
sudo usermod -a -G gpio,i2c pi
# Log out and back in for the changes to take effect.
groups pi  # Should include both gpio and i2c
```

#### 2. Install and enable the service

```bash
# Copy the service file (adjust path if the repo is not at /home/pi/pHox2)
sudo cp /home/pi/pHox2/deploy/phox2-co3-gui.service /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable phox2-co3-gui   # start automatically on every boot
sudo systemctl start phox2-co3-gui    # start now without rebooting
```

#### 3. Verify it is running

```bash
sudo systemctl status phox2-co3-gui
```

The service takes a few seconds to initialise hardware. Once running, the GUI is available:
- On the Pi itself: http://localhost:8000
- From another machine: `http://<raspberry-pi-ip>:8000`

If you have UFW active, allow port 8000 first:

```bash
sudo ufw allow 8000
```

#### 4. View live logs

```bash
journalctl -u phox2-co3-gui -f
```

#### 5. Stop or disable

```bash
sudo systemctl stop phox2-co3-gui     # stop now (hardware reaches safe state)
sudo systemctl disable phox2-co3-gui  # do not start on next boot
```

#### Customising interval and salinity

Edit `configs/co3_config.yaml` before copying the service file:

```yaml
continuous:
  interval_s: 300    # seconds between measurements
  autostart: true    # must be true for the service to start measurements automatically

measurement:
  salinity: 35.0     # default salinity (PSU) when Ferrybox is not providing live data
```

Alternatively, override individual keys in the `ExecStart` line of the service file and
reload: `sudo systemctl daemon-reload && sudo systemctl restart phox2-co3-gui`.

#### Cron alternative (simpler, no restart-on-failure)

If you only need scheduled single measurements rather than a persistent GUI + loop:

```bash
crontab -e

# CO3 every hour, log to file:
0 * * * * cd /home/pi/pHox2 && .venv/bin/python scripts/run_single_measurement.py \
  --config-name co3_config hardware.use_mock=false >> ~/phox2.log 2>&1
```

---

## Configuration

Configuration is split by instrument type. Both files follow the same structure and are loaded via Hydra — any key can be overridden on the command line.

| Config file | Instrument |
|-------------|------------|
| `configs/co3_config.yaml` | CO₃ carbonate measurement |
| `configs/ph_config.yaml` | pH measurement |

### Key Parameters

| Parameter | Description | Default (CO₃ / pH) |
|-----------|-------------|---------------------|
| `hardware.use_mock` | Simulated (true) or real hardware (false) | `true` |
| `measurement.n_cycles` | Dye injection + absorbance cycles per run | `1` / `4` |
| `measurement.pump_time_s` | Sample flush duration before measurement | `60.0 s` |
| `measurement.mix_time_s` | Stirring time after dye injection | `10.0 s` |
| `measurement.drain_after` | Drain cuvette after measurement | `true` |
| `measurement.time_acceleration` | Divide all sleep times by this factor | `100` (mock) |
| `spectrometer.integration_time_ms` | Spectrometer integration time | `18.0 ms` |
| `spectrometer.n_averages` | Spectra averaged per reading | `6` |
| `temperature.calibration_coefficients` | `[slope, intercept]` for ADC→°C conversion | `[-1.234, 15.678]` |
| `output.base_path` | Root directory for measurement data files | `~/phox_data` |
| `ferrybox.enabled` | Enable Ferrybox UDP communication | `false` |

See `configs/co3_config.yaml` and `configs/ph_config.yaml` for all available options.

---

## Output and Data

### Hydra Run Outputs

Each script invocation creates a Hydra output directory:
```
outputs/<YYYY-MM-DD>/<HH-MM-SS>/
  .hydra/config.yaml    # full configuration snapshot
  <script>.log          # console log
```

### Measurement Data Files

Measurement data is written to `~/phox_data/` (configurable via `output.base_path`):

```
~/phox_data/
  data_co3/
    CO3.log               # one-row summary appended after each CO3 measurement
    <timestamp>.spt       # transposed intensity spectra
    <timestamp>.evl       # per-injection intermediate values
  data_ph/
    pH.log
    <timestamp>.spt
    <timestamp>.evl
```

---

## Troubleshooting

### Regular System Issues

**Import errors**: Ensure the package is installed:
```bash
uv sync
```

**Mock hardware not working**: Verify Python 3.11+ is in use:
```bash
python3 --version
```

### Raspberry Pi Issues

**GPIO access denied**: Ensure user is in `gpio` group:
```bash
groups $USER  # Should include 'gpio'
# If not: sudo usermod -a -G gpio $USER  (then log out and back in)
```

**I²C device not found**: Check I²C is enabled and device is powered:
```bash
sudo raspi-config nonint get_i2c  # Should return 0 if enabled
i2cdetect -y 1
```

**Spectrometer not detected**: Verify USB connection and driver:
```bash
lsusb | grep -i "ocean"
```

**Permission denied on GPIO**: Ensure your user is in the `gpio` group:
```bash
sudo usermod -a -G gpio $USER
# Log out and back in for the change to take effect
```

---

## Development

### Running Tests

```bash
uv sync --extra dev
uv run pytest tests/
```

### Project Structure

```
phox2/
├── src/phox2/
│   ├── co3_api.py          # CO3InstrumentAPI — public entry point for CO3
│   ├── ph_api.py           # pHInstrumentAPI  — public entry point for pH
│   ├── factory.py          # InstrumentFactory — only place that wires concrete hardware
│   ├── components/         # Higher-level component wrappers (valve, pump, LED, etc.)
│   ├── hardware/           # ABCs + mock/ and real/ concrete drivers
│   ├── measurement/        # Cycle orchestration (co3_cycle.py, ph_cycle.py) + frozen dataclass models
│   ├── physics/            # Pure functions: CO3 and pH calculations (no I/O)
│   ├── communication/      # IFerryboxClient ABC + FerryboxUDPClient / NullFerryboxClient
│   ├── storage/            # FileStorage — writes .spt / .evl / .log files
│   └── gui/                # FastAPI + WebSocket server + Vue 3 SPA
├── configs/
│   ├── co3_config.yaml     # CO3 instrument configuration
│   └── ph_config.yaml      # pH instrument configuration
├── scripts/
│   ├── run_single_measurement.py    # Run one CO3 or pH measurement cycle
│   ├── run_continuous_measurement.py # Run cycles in a loop with configurable interval
│   └── run_gui.py                   # Launch the FastAPI web GUI
└── tests/                  # pytest-asyncio integration tests (mock hardware)
```

---
