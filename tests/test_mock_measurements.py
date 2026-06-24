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


_QC_FIELDS = (
    "qc_flow",
    "qc_dye",
    "qc_biofouling",
    "qc_temp_sensor",
    "qc_udp",
    "qc_overall",
)
_FB_FIELDS = ("fb_pumping", "longitude", "latitude", "box_id")


async def test_co3_result_has_new_fields(co3_cfg: DictConfig) -> None:
    async with CO3InstrumentAPI.from_config(co3_cfg) as api:
        result = await api.run_single_measurement(flush_before=False)
    for f in _QC_FIELDS + _FB_FIELDS:
        assert hasattr(result, f), f"missing field {f}"
    # QC flags are populated (booleans) after a cycle.
    assert isinstance(result.qc_biofouling, bool)
    assert isinstance(result.qc_overall, bool)
    assert result.box_id  # from ship.box_id
    payload = result.to_udp_payload()
    assert "qc_overall" in payload and "longitude" in payload


async def test_ph_result_has_new_fields(ph_cfg: DictConfig) -> None:
    async with pHInstrumentAPI.from_config(ph_cfg) as api:
        result = await api.run_single_measurement(flush_before=False)
    for f in _QC_FIELDS + _FB_FIELDS:
        assert hasattr(result, f), f"missing field {f}"
    assert isinstance(result.qc_biofouling, bool)
    # pH runs 4 injections → temperature readings vary → temp-sensor QC passes.
    assert result.qc_temp_sensor is True
    payload = result.to_udp_payload()
    assert payload["perturbation"] == result.slope


def test_evaluate_qc_logic() -> None:
    """The pure QC function applies the original thresholds."""
    import numpy as np

    from phox2.measurement.qc import evaluate_qc

    dark = np.full(10, 100.0)
    blank = np.full(10, 1000.0)
    inj0 = np.full(10, 800.0)        # blank − inj0 = 200 > 5 → dye good
    injections = {0: inj0}
    qc = evaluate_qc(
        dark=dark,
        blank=blank,
        injection_spectra=injections,
        voltages=[0.1, 0.2, 0.3],     # vary → temp sensor alive
        blue_px=0,
        blue_now=800.0 + 5000.0,      # well above last injection + threshold
        integration_time_ms=18.0,     # < 2000 → no biofouling
        fb_pumping=1,                 # connection alive
        flow_threshold=2000.0,
    )
    assert qc.flow is True
    assert qc.dye is True
    assert qc.biofouling is True
    assert qc.temp_sensor is True
    assert qc.udp is True
    assert qc.overall is True

    # Stuck temp probe + fouled window + pump off → fails.
    qc2 = evaluate_qc(
        dark=dark,
        blank=blank,
        injection_spectra=injections,
        voltages=[0.5, 0.5, 0.5],
        blue_px=0,
        blue_now=800.0,
        integration_time_ms=2500.0,
        fb_pumping=None,
        flow_threshold=2000.0,
    )
    assert qc2.flow is False
    assert qc2.biofouling is False
    assert qc2.temp_sensor is False
    assert qc2.udp is False
    assert qc2.overall is False


def test_ferrybox_protocol_parses_new_fields() -> None:
    """The Ferrybox JSON protocol extracts pumping/longitude/latitude."""
    from phox2.communication.udp_client import _FerryboxProtocol

    received: list = []
    proto = _FerryboxProtocol()
    proto.add_callback(received.append)
    proto.datagram_received(
        b'{"type": "ferrybox_data", "salinity": 34.5, "temperature": 12.0, '
        b'"pumping": 1, "longitude": 10.71, "latitude": 59.91}',
        ("127.0.0.1", 5555),
    )
    assert len(received) == 1
    fb = received[0]
    assert fb.salinity == pytest.approx(34.5)
    assert fb.pumping == 1
    assert fb.longitude == pytest.approx(10.71)
    assert fb.latitude == pytest.approx(59.91)


async def test_ph_log_columns_match_spec(ph_cfg: DictConfig, tmp_path) -> None:
    """pH log header matches the original column order."""
    from phox2.storage.file_storage import pHFileStorage

    async with pHInstrumentAPI.from_config(ph_cfg) as api:
        result = await api.run_single_measurement(flush_before=False)
    storage = pHFileStorage(tmp_path)
    storage.save(result)
    log_file = tmp_path / "data_pH" / "pH.log"
    header = log_file.read_text().splitlines()[0].split(",")
    assert header == [
        "Time", "Lon", "Lat", "fb_temp", "fb_sal", "SHIP",
        "pH_cuvette", "T_cuvette", "perturbation", "evalAnir",
        "pH_insitu", "r_square", "box_id",
        "flow_QC", "dye_coming_qc", "biofouling_qc",
        "temp_sens_qc", "UDP_conn_qc", "overall_qc",
    ]
