# CO3 Seawater Spectrophotometric Instrument

A modular Python package for autonomous CO3 seawater carbonate measurement using spectrophotometry. Supports both mock hardware (for development/testing) and real hardware deployment on Raspberry Pi.

## Overview

This instrument measures seawater carbonate ion (CO3²⁻) concentration using optical spectroscopy combined with pH-indicator dyes. The package handles:

- **Hardware control**: pumps, valves, spectrometer, ADC, temperature probes, and relays
- **Measurement cycles**: automated sample preparation, equilibration, and optical measurement
- **Data acquisition**: spectral data, temperature measurements, and quality control
- **Configuration management**: hardware pins, calibration coefficients, and measurement parameters

## Quick Start

### Regular System (Mock Hardware)

Perfect for development, testing, and non-hardware environments.

#### Prerequisites

- Python 3.11 or later
- `uv` package manager (recommended) or `pip`

#### Installation

```bash
# Clone/navigate to the repository
cd /path/to/co3_instrument

# Install in development mode
uv sync

# Or with pip:
pip install -e .
```

#### Run a Measurement

```bash
# Default: uses mock hardware (simulated devices)
uv run scripts/run_single_measurement.py
```

The measurement will:
1. Perform a simulated measurement cycle
2. Output results to `outputs/<date>/<time>/` with configuration snapshot and logs
3. Save measurement data to `~/co3_data/`

#### Common Overrides

```bash
# Run with custom salinity (default: 35.0 PSU)
uv run scripts/run_single_measurement.py measurement.salinity=34.5

# Skip drain cycle (useful for bench testing)
uv run scripts/run_single_measurement.py measurement.drain_after=false

# Override multiple parameters
uv run scripts/run_single_measurement.py hardware.use_mock=true measurement.salinity=34.2
```

---

## Raspberry Pi Deployment

Instructions for installing and running on real hardware with a Raspberry Pi.

### Prerequisites

**Hardware:**
- Raspberry Pi 4 or later (4GB+ RAM recommended)
- Freshly imaged Raspberry Pi OS (Bookworm or later)
- Physical CO3 instrument hardware connected to GPIO pins and I²C

**Software:**
- Python 3.11 or later
- `uv` or `pip` for package management

### Installation on Raspberry Pi

#### 1. Update System

```bash
sudo apt update
sudo apt upgrade -y
```

#### 2. Install Python and Build Tools

```bash
sudo apt install -y python3.11 python3.11-venv python3.11-dev build-essential
```

#### 3. Install Hardware Libraries (System-Level)

The real hardware drivers require system packages:

```bash
# For I²C (ADC, spectrometer communication)
sudo apt install -y i2c-tools python3-smbus

# For GPIO and PWM control via pigpio daemon
sudo apt install -y pigpio python3-pigpio

# Start pigpio daemon on boot
sudo systemctl enable pigpiod
sudo systemctl start pigpiod

# For USB spectrometer (Ocean Insight SeaBreeze)
# Install libusb for SeaBreeze spectrometer support
sudo apt install -y libusb-1.0-0 libusb-1.0-0-dev

# Configure user to access GPIO without sudo
sudo usermod -a -G gpio $USER
# Log out and back in for group changes to take effect
```

#### 4. Configure I²C

Enable I²C interface:

```bash
sudo raspi-config nonint set_i2c 0  # Enable I²C
```

Verify I²C devices are visible:

```bash
i2cdetect -y 1
```

#### 5. Clone and Install the Package

```bash
# Clone or navigate to the repository
cd /path/to/co3_instrument

# Install with real hardware dependencies
uv sync --extra hardware

# Or with pip:
pip install -e ".[hardware]"
```

#### 6. Update Configuration

Edit `configs/config.yaml` to match your hardware setup:

```yaml
hardware:
  use_mock: false          # Enable real hardware

gpio:
  # Verify these match your physical wiring (BCM pin numbers)
  valve_enable_pin: 24
  valve_ch1_pin: 23
  valve_ch2_pin: 25
  water_pump_pin: 21
  dye_pump_pin: 19
  stirrer_pin: 20
  drain_pin: 16
  air_pin: 26
  light_pin: 17
  shutter_pin: 27

adc:
  temperature_channel: 8     # I²C channel for temperature ADC

spectrometer:
  integration_time_ms: 18.0  # Adjust for your spectrometer
```

#### 7. Test Hardware Communication

Before running measurements, verify hardware is accessible:

```bash
# Check GPIO is accessible
python3 -c "import pigpio; pi = pigpio.pi(); print('GPIO OK')"

# Check I²C devices
i2cdetect -y 1

# Check spectrometer connection (if USB)
lsusb | grep "Ocean Insight"
```

### Run a Measurement on Raspberry Pi

```bash
# Run with real hardware
uv run scripts/run_single_measurement.py hardware.use_mock=false

# With custom salinity
uv run scripts/run_single_measurement.py hardware.use_mock=false measurement.salinity=34.5

# View help for all configuration options
uv run scripts/run_single_measurement.py --help
```

### Automated Measurements

To run measurements on a schedule, use a cron job:

```bash
# Edit crontab
crontab -e

# Add a daily measurement at 12:00 UTC (adjust time as needed):
0 12 * * * cd /path/to/co3_instrument && /usr/bin/python3 -m venv /tmp/co3_venv && \
  source /tmp/co3_venv/bin/activate && \
  uv sync --extra hardware && \
  uv run scripts/run_single_measurement.py hardware.use_mock=false >> ~/co3_instrument.log 2>&1
```

Or use a systemd timer for more control (see below for an example setup).

---

## Configuration

All configuration is managed through `configs/config.yaml` (loaded via Hydra) and can be overridden on the command line.

### Key Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `hardware.use_mock` | Use simulated hardware (true) or real hardware (false) | `true` |
| `measurement.salinity` | Seawater salinity in PSU | `35.0` |
| `measurement.drain_after` | Drain cuvette after measurement | `true` |
| `spectrometer.integration_time_ms` | Spectrometer integration time | `18.0` |
| `spectrometer.n_averages` | Number of averages per measurement | `6` |
| `temperature.calibration_coefficients` | Temperature probe calibration | `[-1.234, 15.678]` |

See `configs/config.yaml` for all available options.

---

## Output and Data

### Measurement Outputs

Each measurement creates an output directory at:
```
outputs/<YYYY-MM-DD>/<HH-MM-SS>/
```

Contains:
- `.hydra/config.yaml` — Full configuration snapshot
- Measurement logs and data files

### Data Storage

Measurement data is saved to:
```
~/co3_data/
```

Includes spectral data, temperature readings, and computed CO3 concentrations.

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
groups $USER  # Should show 'gpio'
# If not, run: sudo usermod -a -G gpio $USER (then log out and back in)
```

**I²C device not found**: Check I²C is enabled and device is powered:
```bash
sudo raspi-config nonint get_i2c  # Should return 0 if enabled
i2cdetect -y 1
```

**Spectrometer not detected**: Verify USB connection and driver:
```bash
lsusb | grep "Ocean Insight"
```

**Permission denied on pigpio**: Ensure pigpiod daemon is running:
```bash
sudo systemctl status pigpiod
sudo systemctl restart pigpiod
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
co3_instrument/
├── src/co3_instrument/
│   ├── api.py              # Main API entry point
│   ├── factory.py          # Hardware factory (mock/real)
│   ├── components/         # Hardware abstraction (pump, valve, etc.)
│   ├── hardware/           # Real and mock hardware drivers
│   ├── measurement/        # Measurement cycle logic
│   ├── physics/            # CO3 calculation algorithms
│   └── storage/            # Data file I/O
├── configs/
│   └── config.yaml         # Configuration template
├── scripts/
│   └── run_single_measurement.py  # CLI entry point
└── tests/                  # Test suite
```

---

## License

[Your License Here]

## Contact

For questions or issues, contact the instrument team.
