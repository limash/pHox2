"""
run_continuous_measurement.py — continuous CO3 or pH measurement loop.

Runs measurement cycles back-to-back with a configurable inter-measurement
wait, printing a compact one-line summary after each result.  Press Ctrl-C
(or send SIGTERM) to stop safely: the current measurement runs to completion,
hardware cleanup happens via the API context manager, then the script exits.

Usage
-----
From the project root (a --config-name is always required):

    # CO3 — mock hardware, 60-second interval:
    uv run scripts/run_continuous_measurement.py --config-name co3_config continuous.interval_s=60

    # pH — mock hardware, default 300-second interval:
    uv run scripts/run_continuous_measurement.py --config-name ph_config

    # Real hardware, 5-minute interval:
    uv run scripts/run_continuous_measurement.py --config-name co3_config \\
        hardware.use_mock=false continuous.interval_s=300

Overridable Hydra keys (no config-file change needed):
    continuous.interval_s   — seconds to wait between measurements (default 300)
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

import hydra
from omegaconf import DictConfig, OmegaConf

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from phox2.co3_api import CO3InstrumentAPI
from phox2.ph_api import pHInstrumentAPI
from phox2.storage.file_storage import CO3FileStorage, pHFileStorage

logger = logging.getLogger(__name__)

@hydra.main(
    version_base=None,
    config_path=str(Path(__file__).parent.parent / "configs"),
    config_name=None,
)
def main(cfg: DictConfig) -> None:
    """Hydra entry point — runs CO3 or pH measurement cycles continuously."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    instrument_type: str = str(
        OmegaConf.select(cfg, "instrument_type", default="co3")
    ).lower()

    interval_s: float = float(cfg.continuous.interval_s)

    logger.info("=" * 60)
    logger.info("%s Instrument — Continuous Measurement", instrument_type.upper())
    logger.info("  hardware.use_mock = %s", cfg.hardware.use_mock)
    logger.info("  interval_s        = %.0f s", interval_s)
    logger.info("  Press Ctrl-C to stop safely after the current measurement.")
    logger.info("=" * 60)

    if instrument_type == "ph":
        asyncio.run(_run_ph(cfg, interval_s))
    else:
        asyncio.run(_run_co3(cfg, interval_s))


async def _run_co3(cfg: DictConfig, interval_s: float) -> None:
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    storage = CO3FileStorage(cfg.output.base_path)
    measurement_n = 0

    async with CO3InstrumentAPI.from_config(cfg) as api:
        while not stop_event.is_set():
            measurement_n += 1
            logger.info("Starting CO3 measurement #%d…", measurement_n)

            try:
                result = await api.run_single_measurement(
                    flush_before=(measurement_n > 1),
                )
            except Exception:
                logger.exception("Measurement #%d failed — will retry after interval", measurement_n)
            else:
                ts = result.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                print(
                    f"[{ts}]  #{measurement_n}"
                    f"  CO3={result.co3_umol_per_kg:>8.2f} µmol/kg"
                    f"  T={result.t_cuvette:.2f}°C"
                    f"  S={result.salinity_corrected:.3f} PSU"
                    f"  R={result.r_ratio:.4f}",
                    flush=True,
                )
                storage.save(result)

            if stop_event.is_set():
                break

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_s)
                # stop_event fired before timeout — exit loop
                break
            except asyncio.TimeoutError:
                pass  # interval elapsed → run next measurement

    logger.info("CO3 continuous measurement stopped. Hardware cleaned up.")


async def _run_ph(cfg: DictConfig, interval_s: float) -> None:
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    storage = pHFileStorage(cfg.output.base_path)
    measurement_n = 0

    async with pHInstrumentAPI.from_config(cfg) as api:
        while not stop_event.is_set():
            measurement_n += 1
            logger.info("Starting pH measurement #%d…", measurement_n)

            try:
                result = await api.run_single_measurement(
                    flush_before=(measurement_n > 1),
                )
            except Exception:
                logger.exception("Measurement #%d failed — will retry after interval", measurement_n)
            else:
                ts = result.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                print(
                    f"[{ts}]  #{measurement_n}"
                    f"  pH={result.pH_cuvette:.4f}"
                    f"  pH_insitu={result.pH_insitu:.4f}"
                    f"  r²={result.r_square:.4f}"
                    f"  T={result.t_cuvette:.2f}°C"
                    f"  S={result.salinity_corrected:.3f} PSU",
                    flush=True,
                )
                storage.save(result)

            if stop_event.is_set():
                break

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_s)
                break
            except asyncio.TimeoutError:
                pass


    logger.info("pH continuous measurement stopped. Hardware cleaned up.")


if __name__ == "__main__":
    main()
