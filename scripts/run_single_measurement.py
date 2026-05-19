"""
run_single_measurement.py — entry point for a single CO3 or pH measurement cycle.

Usage
-----
From the project root (a --config-name is always required):

    # CO3 — mock hardware:
    uv run scripts/run_single_measurement.py --config-name co3_config

    # pH — mock hardware:
    uv run scripts/run_single_measurement.py --config-name ph_config

    # Real hardware on Raspberry Pi:
    uv run scripts/run_single_measurement.py hardware.use_mock=false

    # Override salinity:
    uv run scripts/run_single_measurement.py measurement.salinity=34.5

    # Fast run without draining (useful during bench testing):
    uv run scripts/run_single_measurement.py measurement.drain_after=false

Hydra will create an output folder (outputs/<date>/<time>/) containing the
config snapshot and logs.  Measurement data files are written to ~/co3_data/.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import hydra
from omegaconf import DictConfig, OmegaConf

# Ensure the package is importable when running from the scripts/ directory
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from phox2.co3_api import CO3InstrumentAPI
from phox2.ph_api import pHInstrumentAPI
from phox2.storage.file_storage import CO3FileStorage, pHFileStorage

logger = logging.getLogger(__name__)

# Default salinity if not provided by Ferrybox UDP
_DEFAULT_SALINITY = 35.0


@hydra.main(
    version_base=None,
    config_path=str(Path(__file__).parent.parent / "configs"),
    config_name=None,
)
def main(cfg: DictConfig) -> None:
    """Hydra entry point — runs one complete CO3 or pH measurement cycle."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    instrument_type: str = str(
        OmegaConf.select(cfg, "instrument_type", default="co3")
    ).lower()

    salinity: float = float(
        OmegaConf.select(cfg, "measurement.salinity", default=_DEFAULT_SALINITY)
    )

    logger.info("=" * 60)
    logger.info("%s Instrument — Single Measurement", instrument_type.upper())
    logger.info("  hardware.use_mock = %s", cfg.hardware.use_mock)
    logger.info("  salinity          = %.3f PSU", salinity)
    logger.info("  n_cycles          = %d", cfg.measurement.n_cycles)
    logger.info("  time_acceleration = %dx", cfg.measurement.time_acceleration)
    logger.info("=" * 60)

    if instrument_type == "ph":
        asyncio.run(_async_main_ph(cfg, salinity))
    else:
        asyncio.run(_async_main_co3(cfg, salinity))


async def _async_main_co3(cfg: DictConfig, salinity: float) -> None:
    async with CO3InstrumentAPI.from_config(cfg) as api:
        # ── Optional: show live spectrum before measuring ──────────────
        logger.info("Capturing pre-measurement spectrum…")
        api.turn_on_light()
        api.open_shutter()
        spectrum = await api.get_spectrum()
        logger.info(
            "  Peak intensity: %.0f counts at pixel %d",
            spectrum.max(), int(spectrum.argmax()),
        )

        # ── Run the measurement ───────────────────────────────────────
        result = await api.run_single_measurement(
            salinity=salinity,
            flush_before=False,
        )

        # ── Print results ─────────────────────────────────────────────
        print()
        print("─" * 60)
        print("  CO3 MEASUREMENT RESULT")
        print("─" * 60)
        print(f"  [CO3²⁻]     = {result.co3_umol_per_kg:>10.2f}  µmol/kg")
        print(f"  T cuvette   = {result.t_cuvette:>10.3f}  °C")
        print(f"  S input     = {result.salinity_input:>10.3f}  PSU")
        print(f"  S corrected = {result.salinity_corrected:>10.3f}  PSU")
        print(f"  A1 (234 nm) = {result.a1:>10.5f}")
        print(f"  A2 (250 nm) = {result.a2:>10.5f}")
        print(f"  A3 (350 nm) = {result.a3:>10.5f}")
        print(f"  R ratio     = {result.r_ratio:>10.4f}")
        print(f"  e1          = {result.e1:>10.6f}")
        print(f"  e3e2        = {result.e3e2:>10.6f}")
        print(f"  log β₁/ε₂  = {result.log_beta1_e2:>10.6f}")
        print(f"  Dye         = {result.dye}")
        print(f"  Timestamp   = {result.timestamp.isoformat(timespec='seconds')}")
        print("─" * 60)
        print()

        # ── Save to disk ───────────────────────────────────────────────
        storage = CO3FileStorage(cfg.output.base_path)
        storage.save(result)
        logger.info("Results saved to %s/data_co3/", cfg.output.base_path)


async def _async_main_ph(cfg: DictConfig, salinity: float) -> None:
    async with pHInstrumentAPI.from_config(cfg) as api:
        # ── Show live spectrum before measuring ────────────────────────
        logger.info("Capturing pre-measurement spectrum…")
        api.turn_on_leds()
        spectrum = await api.get_spectrum()
        logger.info(
            "  Peak intensity: %.0f counts at pixel %d",
            spectrum.max(), int(spectrum.argmax()),
        )

        # ── Run the measurement ───────────────────────────────────────
        result = await api.run_single_measurement(
            salinity=salinity,
            flush_before=False,
        )

        # ── Print results ─────────────────────────────────────────────
        dye = result.dye
        wl2 = 578 if dye == "MCP" else 596
        print()
        print("─" * 60)
        print("  pH MEASUREMENT RESULT")
        print("─" * 60)
        print(f"  pH cuvette  = {result.pH_cuvette:>10.4f}")
        print(f"  pH in-situ  = {result.pH_insitu:>10.4f}")
        print(f"  r²          = {result.r_square:>10.4f}")
        print(f"  T cuvette   = {result.t_cuvette:>10.3f}  °C")
        print(f"  S input     = {result.salinity_input:>10.3f}  PSU")
        print(f"  S corrected = {result.salinity_corrected:>10.3f}  PSU")
        print(f"  A1 (434 nm) = {result.a1:>10.5f}")
        print(f"  A2 ({wl2} nm) = {result.a2:>10.5f}")
        print(f"  A NIR       = {result.a_nir:>10.5f}")
        print(f"  R ratio     = {result.r_ratio:>10.4f}")
        print(f"  e1          = {result.e1:>10.6f}")
        print(f"  e2e3        = {result.e2e3:>10.6f}")
        print(f"  pK          = {result.pK:>10.6f}")
        print(f"  Dye         = {result.dye}")
        print(f"  Timestamp   = {result.timestamp.isoformat(timespec='seconds')}")
        print("─" * 60)
        print()

        # ── Save to disk ───────────────────────────────────────────────
        storage = pHFileStorage(cfg.output.base_path)
        storage.save(result)
        logger.info("Results saved to %s/data_pH/", cfg.output.base_path)


if __name__ == "__main__":
    main()
