"""
run_gui.py — Launch the phox2 web GUI.

Starts a FastAPI server that wraps the CO3 or pH instrument API and serves
a Vue 3 single-page app accessible from any browser on the local network.

Usage
-----
From the project root (--config-name is always required):

    # CO3 — mock hardware:
    uv run scripts/run_gui.py --config-name co3_config

    # pH — mock hardware:
    uv run scripts/run_gui.py --config-name ph_config

    # Real hardware on Raspberry Pi:
    uv run scripts/run_gui.py --config-name co3_config hardware.use_mock=false

    # Custom interval and port:
    uv run scripts/run_gui.py --config-name co3_config continuous.interval_s=120

Then open http://localhost:8000 in any browser, or http://<pi-ip>:8000 from
another machine on the same network.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import hydra
from omegaconf import DictConfig

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@hydra.main(
    version_base=None,
    config_path=str(Path(__file__).parent.parent / "configs"),
    config_name=None,
)
def main(cfg: DictConfig) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    import uvicorn

    from phox2.gui.app import create_app

    instrument_type = str(cfg.get("instrument_type", "co3")).lower()
    config_path = Path(__file__).parent.parent / "configs" / f"{instrument_type}_config.yaml"

    app = create_app(cfg, config_path=config_path)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    main()
