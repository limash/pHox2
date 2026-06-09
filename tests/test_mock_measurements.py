"""
Integration tests for CO3 and pH mock measurement cycles.

Loads configs via OmegaConf directly (no Hydra) so that no output
directories are created and the tests run with standard pytest.
Both instruments are configured with hardware.use_mock=true and
time_acceleration=100, so the full cycle completes in seconds.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from omegaconf import DictConfig, OmegaConf

from phox2.co3_api import CO3InstrumentAPI
from phox2.measurement.models import CO3MeasurementResult, pHMeasurementResult
from phox2.ph_api import pHInstrumentAPI

_CONFIGS = Path(__file__).parent.parent / "configs"


@pytest.fixture
def co3_cfg() -> DictConfig:
    cfg = OmegaConf.load(_CONFIGS / "co3_config.yaml")
    assert isinstance(cfg, DictConfig)
    return cfg


@pytest.fixture
def ph_cfg() -> DictConfig:
    cfg = OmegaConf.load(_CONFIGS / "ph_config.yaml")
    assert isinstance(cfg, DictConfig)
    return cfg


async def test_co3_mock_measurement(co3_cfg: DictConfig) -> None:
    async with CO3InstrumentAPI.from_config(co3_cfg) as api:
        result = await api.run_single_measurement(flush_before=False)
        assert isinstance(result, CO3MeasurementResult)
        assert isinstance(result.co3_umol_per_kg, float)
        assert isinstance(result.t_cuvette, float)
        assert result.salinity_input == pytest.approx(35.0)


async def test_ph_mock_measurement(ph_cfg: DictConfig) -> None:
    async with pHInstrumentAPI.from_config(ph_cfg) as api:
        result = await api.run_single_measurement(flush_before=False)
        assert isinstance(result, pHMeasurementResult)
        assert isinstance(result.pH_cuvette, float)
        assert isinstance(result.t_cuvette, float)
        assert result.salinity_input == pytest.approx(35.0)
        assert 0.0 <= result.r_square <= 1.0
