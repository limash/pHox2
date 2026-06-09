"""
FastAPI web application for the phox2 instrument GUI.

Serves a Vue 3 single-page app and exposes a WebSocket endpoint for
bidirectional communication between the browser and the instrument API.

All hardware interaction goes through CO3InstrumentAPI / pHInstrumentAPI;
no hardware drivers are imported here.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from omegaconf import DictConfig, OmegaConf

from phox2.co3_api import CO3InstrumentAPI
from phox2.measurement.models import CO3MeasurementResult, pHMeasurementResult
from phox2.ph_api import pHInstrumentAPI
from phox2.storage.file_storage import CO3FileStorage, pHFileStorage

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"
_HISTORY_ROWS = 50


# ── JSON helpers ──────────────────────────────────────────────────────────────

def _json_default(obj: Any) -> Any:
    if isinstance(obj, np.floating):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Not JSON serializable: {type(obj)}")


def _dumps(msg: dict) -> str:
    return json.dumps(msg, default=_json_default)


# ── Connection manager ────────────────────────────────────────────────────────

class ConnectionManager:
    """Maintains the set of active WebSocket connections and broadcasts to all."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)

    async def broadcast(self, msg: dict) -> None:
        if not self._connections:
            return
        data = _dumps(msg)
        dead: set[WebSocket] = set()
        for ws in list(self._connections):
            try:
                await ws.send_text(data)
            except Exception:
                dead.add(ws)
        self._connections -= dead


# ── Log forwarding ────────────────────────────────────────────────────────────

class WebSocketLogHandler(logging.Handler):
    """Forwards log records to all connected WebSocket clients."""

    def __init__(self, manager: ConnectionManager) -> None:
        super().__init__()
        self._manager = manager

    def emit(self, record: logging.LogRecord) -> None:
        try:
            asyncio.ensure_future(
                self._manager.broadcast({"type": "log_line", "text": self.format(record)})
            )
        except Exception:
            self.handleError(record)


# ── Instrument state + background tasks ───────────────────────────────────────

class InstrumentState:
    """
    Owns the instrument API instance and all background asyncio tasks.

    Coordinates measurement execution, mode transitions, and broadcasts state
    changes to all connected WebSocket clients. The GUI never imports hardware
    drivers — it only calls methods on this class.
    """

    def __init__(
        self,
        cfg: DictConfig,
        manager: ConnectionManager,
        config_path: Path | None = None,
    ) -> None:
        self._cfg = cfg
        self._manager = manager
        self._config_path = config_path

        self.instrument_type: str = str(
            OmegaConf.select(cfg, "instrument_type", default="co3")
        ).lower()

        self._api: CO3InstrumentAPI | pHInstrumentAPI | None = None
        self._storage: CO3FileStorage | pHFileStorage | None = None

        # Mode set — single source of truth for widget enable/disable
        self.modes: set[str] = set()
        self.measurement_n: int = 0
        self.last_result: dict | None = None
        self.wavelengths: list[float] = []

        self._spectrum_paused: bool = False
        self._stop_continuous: asyncio.Event = asyncio.Event()

        self._continuous_task: asyncio.Task | None = None
        self._sensor_task: asyncio.Task | None = None
        self._spectrum_task: asyncio.Task | None = None
        self._countdown_task: asyncio.Task | None = None
        self._next_measurement_at: float | None = None

        self.interval_s: float = float(
            OmegaConf.select(cfg, "continuous.interval_s", default=300.0)
        )
        self._autostart: bool = bool(
            OmegaConf.select(cfg, "continuous.autostart", default=False)
        )
        self.n_cycles: int = int(
            OmegaConf.select(cfg, "measurement.n_cycles", default=1)
        )

        int_time_ms = float(
            OmegaConf.select(cfg, "spectrometer.integration_time_ms", default=18.0)
        )
        self._config_integration_time_ms: float = int_time_ms
        self._spectrum_interval_s = (
            int_time_ms + max(200.0, min(int_time_ms * 2.0, 1000.0))
        ) / 1000.0

        # Tracked config values (kept in sync with cfg for save_config)
        dye_key = "ph.dye" if self.instrument_type == "ph" else "co3.dye"
        self._config_dye: str = str(OmegaConf.select(cfg, dye_key, default=""))
        self._config_autoadjust: str = str(
            OmegaConf.select(cfg, "spectrometer.autoadjust.mode", default="ON")
        )
        self._config_pump_time_s: float = float(
            OmegaConf.select(cfg, "measurement.pump_time_s", default=60.0)
        )
        self._config_manual_pump_duration_s: float = float(
            OmegaConf.select(cfg, "measurement.manual_pump_duration_s", default=1.0)
        )
        self._config_drain_mode: str = (
            "ON" if OmegaConf.select(cfg, "measurement.drain_after", default=True) else "OFF"
        )

        self._base_path: str = str(
            OmegaConf.select(cfg, "output.base_path", default="~/phox_data")
        )

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def startup(self) -> None:
        logger.info("GUI: connecting to %s instrument…", self.instrument_type)
        if self.instrument_type == "ph":
            self._api = pHInstrumentAPI.from_config(self._cfg)
            self._storage = pHFileStorage(self._base_path)
        else:
            self._api = CO3InstrumentAPI.from_config(self._cfg)
            self._storage = CO3FileStorage(self._base_path)

        await self._api.connect()
        self.wavelengths = self._api.wavelengths.tolist()
        logger.info("Instrument connected — %d pixel wavelength array", len(self.wavelengths))

        self._sensor_task = asyncio.create_task(self._sensor_poll(), name="sensor_poll")
        self._spectrum_task = asyncio.create_task(self._spectrum_poll(), name="spectrum_poll")

        if self._autostart:
            logger.info(
                "Autostart: launching continuous measurements (interval=%.0fs)",
                self.interval_s,
            )
            self._continuous_task = asyncio.create_task(
                self._continuous_loop(), name="continuous"
            )

    async def shutdown(self) -> None:
        logger.info("GUI: shutdown — cancelling background tasks…")
        for task in (
            self._continuous_task,
            self._sensor_task,
            self._spectrum_task,
            self._countdown_task,
        ):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        if self._api is not None:
            await self._api.disconnect()

    # ── Background tasks ──────────────────────────────────────────────────

    async def _sensor_poll(self) -> None:
        assert self._api is not None
        while True:
            try:
                t = self._api.get_temperature()
                v = self._api.get_voltage()
                fb = self._api.get_ferrybox_data()
                await self._manager.broadcast(
                    {
                        "type": "sensor_update",
                        "t_cuvette": round(t, 3),
                        "voltage": round(v, 4),
                        "fb_temp": fb.temperature if fb is not None else None,
                        "fb_sal": fb.salinity if fb is not None else None,
                    }
                )
            except Exception:
                logger.debug("Sensor poll error", exc_info=True)
            await asyncio.sleep(0.5)

    async def _spectrum_poll(self) -> None:
        assert self._api is not None
        while True:
            await asyncio.sleep(self._spectrum_interval_s)
            if self._spectrum_paused:
                continue
            try:
                intensities = await self._api.get_spectrum()
                await self._manager.broadcast(
                    {"type": "spectrum_update", "intensities": intensities.tolist()}
                )
            except Exception:
                logger.debug("Spectrum poll error", exc_info=True)

    async def _countdown_loop(self) -> None:
        while "Continuous" in self.modes:
            if self._next_measurement_at is not None:
                remaining = max(
                    0.0,
                    self._next_measurement_at - asyncio.get_running_loop().time(),
                )
                await self._manager.broadcast(
                    {"type": "countdown", "seconds_remaining": int(remaining)}
                )
            await asyncio.sleep(15)

    # ── Measurement ───────────────────────────────────────────────────────

    async def _run_measurement(self, flush_before: bool) -> None:
        self.modes.add("Measuring")
        self._spectrum_paused = True
        await self._broadcast_mode()

        def on_step(step: str) -> None:
            # Called synchronously from within the measurement coroutine;
            # ensure_future is safe here because the event loop is running.
            asyncio.ensure_future(
                self._manager.broadcast({"type": "step_complete", "step": step})
            )

        try:
            assert self._api is not None
            result = await self._api.run_single_measurement(
                flush_before=flush_before,
                on_step=on_step,
            )
            assert self._storage is not None
            self._storage.save(result)
            self.last_result = _serialize_result(result, self.instrument_type)
            await self._manager.broadcast({"type": "measurement_result", **self.last_result})
            logger.info(
                "Measurement #%d complete: %s", self.measurement_n, result.summary()
            )
        except Exception:
            logger.exception("Measurement #%d failed", self.measurement_n)
        finally:
            self.modes.discard("Measuring")
            self._spectrum_paused = False
            await self._broadcast_mode()

    async def _continuous_loop(self) -> None:
        self.modes.add("Continuous")
        self._stop_continuous.clear()
        await self._broadcast_mode()
        self._countdown_task = asyncio.create_task(
            self._countdown_loop(), name="countdown"
        )

        try:
            first = True
            while not self._stop_continuous.is_set():
                self.measurement_n += 1
                await self._run_measurement(flush_before=not first)
                first = False

                if self._stop_continuous.is_set():
                    break

                self._next_measurement_at = (
                    asyncio.get_running_loop().time() + self.interval_s
                )
                try:
                    await asyncio.wait_for(
                        self._stop_continuous.wait(),
                        timeout=self.interval_s,
                    )
                    break
                except asyncio.TimeoutError:
                    pass  # interval elapsed → run next measurement
        finally:
            self._next_measurement_at = None
            self.modes.discard("Continuous")
            if self._countdown_task and not self._countdown_task.done():
                self._countdown_task.cancel()
            await self._broadcast_mode()

    # ── Command dispatcher ────────────────────────────────────────────────

    async def handle_command(self, msg: dict) -> None:  # noqa: C901
        cmd: str = msg.get("cmd", "")
        api = self._api
        assert api is not None

        match cmd:
            case "start_continuous":
                if "Continuous" in self.modes or "Measuring" in self.modes:
                    return
                self._continuous_task = asyncio.create_task(
                    self._continuous_loop(), name="continuous"
                )

            case "stop_continuous":
                self._stop_continuous.set()

            case "start_single":
                if "Measuring" in self.modes:
                    return
                self.measurement_n += 1
                asyncio.create_task(
                    self._run_measurement(flush_before=False),
                    name="single_measurement",
                )

            case "open_valve":
                asyncio.create_task(api.open_valve())
            case "close_valve":
                asyncio.create_task(api.close_valve())

            case "turn_on_light":
                api.turn_on_light()
            case "turn_off_light":
                api.turn_off_light()

            case "open_shutter":
                api.open_shutter()
            case "close_shutter":
                api.close_shutter()

            case "start_stirrer":
                api.start_stirrer()
            case "stop_stirrer":
                api.stop_stirrer()

            case "run_water_pump":
                asyncio.create_task(
                    api.run_water_pump(float(msg.get("duration_s", self._config_manual_pump_duration_s)))
                )
            case "pulse_dye_pump":
                asyncio.create_task(api.pulse_dye_pump(int(msg.get("n_shots", 3))))

            case "drain_cuvette":
                asyncio.create_task(api.drain_cuvette())

            case "auto_adjust":
                if "Adjusting" in self.modes:
                    return

                async def _adjust() -> None:
                    self.modes.add("Adjusting")
                    self._spectrum_paused = True
                    await self._broadcast_mode()
                    try:
                        await api.auto_adjust_integration_time()
                    finally:
                        self.modes.discard("Adjusting")
                        self._spectrum_paused = False
                        await self._broadcast_mode()

                asyncio.create_task(_adjust(), name="auto_adjust")

            # ── Config commands ───────────────────────────────────────

            case "save_config":
                if self._config_path is not None:
                    try:
                        OmegaConf.save(self._cfg, self._config_path)
                        logger.info("Config saved to %s", self._config_path)
                    except Exception:
                        logger.exception("Failed to save config")
                else:
                    logger.warning("save_config: no config_path set")

            case "set_dye_type":
                dye = str(msg.get("dye", ""))
                if not dye:
                    return
                self._config_dye = dye
                dye_key = "ph.dye" if self.instrument_type == "ph" else "co3.dye"
                OmegaConf.update(self._cfg, dye_key, dye)
                await self._broadcast_config()

            case "set_autoadjust":
                mode = str(msg.get("mode", "ON"))
                if mode not in ("ON", "OFF", "ON_NORED"):
                    return
                self._config_autoadjust = mode
                OmegaConf.update(self._cfg, "spectrometer.autoadjust.mode", mode)
                await self._broadcast_config()

            case "set_sampling_interval":
                minutes = float(msg.get("interval_min", 5.0))
                self.interval_s = minutes * 60.0
                OmegaConf.update(self._cfg, "continuous.interval_s", self.interval_s)
                await self._broadcast_config()

            case "set_integration_time":
                time_ms = float(msg.get("time_ms", 18.0))
                self._config_integration_time_ms = time_ms
                self._spectrum_interval_s = (
                    time_ms + max(200.0, min(time_ms * 2.0, 1000.0))
                ) / 1000.0
                OmegaConf.update(self._cfg, "spectrometer.integration_time_ms", time_ms)
                asyncio.create_task(api.set_integration_time(time_ms))
                await self._broadcast_config()

            case "set_drain_mode":
                drain_mode = str(msg.get("mode", "ON"))
                if drain_mode not in ("ON", "OFF"):
                    return
                self._config_drain_mode = drain_mode
                OmegaConf.update(
                    self._cfg, "measurement.drain_after", drain_mode == "ON"
                )
                await self._broadcast_config()

    # ── Helpers ───────────────────────────────────────────────────────────

    async def _broadcast_mode(self) -> None:
        await self._manager.broadcast(
            {
                "type": "mode_change",
                "modes": list(self.modes),
                "measurement_n": self.measurement_n,
            }
        )

    async def _broadcast_config(self) -> None:
        await self._manager.broadcast(
            {"type": "config_update", **self._config_dict()}
        )

    def _config_dict(self) -> dict:
        return {
            "dye": self._config_dye,
            "autoadjust_mode": self._config_autoadjust,
            "pump_time_s": self._config_pump_time_s,
            "manual_pump_duration_s": self._config_manual_pump_duration_s,
            "interval_min": self.interval_s / 60.0,
            "integration_time_ms": self._config_integration_time_ms,
            "drain_mode": self._config_drain_mode,
        }

    def state_snapshot(self) -> dict:
        return {
            "type": "state_snapshot",
            "instrument_type": self.instrument_type,
            "modes": list(self.modes),
            "measurement_n": self.measurement_n,
            "last_result": self.last_result,
            "wavelengths": self.wavelengths,
            "n_cycles": self.n_cycles,
            "interval_s": self.interval_s,
            "config": self._config_dict(),
        }


# ── Result serialisation ──────────────────────────────────────────────────────

def _serialize_result(
    result: CO3MeasurementResult | pHMeasurementResult,
    instrument_type: str,
) -> dict:
    if instrument_type == "co3":
        assert isinstance(result, CO3MeasurementResult)
        spectra = result.spectra
        wl = spectra.wavelengths
        mask = (wl >= 220.0) & (wl <= 360.0)
        dark = spectra.dark[mask]
        blank = spectra.blank[mask]
        denom = np.clip(blank - dark, 1e-9, None)
        absorption_spectra: dict[str, list] = {}
        for idx, inj_arr in spectra.injections.items():
            signal = np.clip(inj_arr[mask] - dark, 1e-9, None)
            absorption = (-np.log10(signal / denom)).tolist()
            absorption_spectra[str(idx)] = absorption
        return {
            "instrument": "co3",
            "timestamp": result.timestamp.isoformat(timespec="seconds"),
            "co3_umol_per_kg": result.co3_umol_per_kg,
            "t_cuvette": result.t_cuvette,
            "salinity_corrected": result.salinity_corrected,
            "r_ratio": result.r_ratio,
            "a1": result.a1,
            "a2": result.a2,
            "a3": result.a3,
            "fb_temp": result.fb_temp,
            "fb_sal": result.fb_sal,
            "absorption_wavelengths": wl[mask].tolist(),
            "absorption_spectra": absorption_spectra,
        }
    assert isinstance(result, pHMeasurementResult)
    return {
        "instrument": "ph",
        "timestamp": result.timestamp.isoformat(timespec="seconds"),
        "pH_cuvette": result.pH_cuvette,
        "pH_insitu": result.pH_insitu,
        "r_square": result.r_square,
        "t_cuvette": result.t_cuvette,
        "salinity_corrected": result.salinity_corrected,
        "r_ratio": result.r_ratio,
        "fb_temp": result.fb_temp,
        "fb_sal": result.fb_sal,
    }


# ── History loading ───────────────────────────────────────────────────────────

def _load_history(instrument_type: str, base_path: str) -> list[dict]:
    base = Path(base_path).expanduser().resolve()
    if instrument_type == "co3":
        log_file = base / "data_co3" / "CO3.log"
        value_col = "co3"
    else:
        log_file = base / "data_pH" / "pH.log"
        value_col = "pH_cuvette"

    if not log_file.exists():
        return []

    try:
        df = pd.read_csv(log_file).tail(_HISTORY_ROWS)
        points: list[dict] = []
        for _, row in df.iterrows():
            point: dict = {
                "timestamp": str(row.get("Time", "")),
                "t_cuvette": float(row.get("T_cuvette", 0.0)),
            }
            if value_col in df.columns:
                point["value"] = float(row[value_col])
            if instrument_type == "ph" and "pH_insitu" in df.columns:
                point["pH_insitu"] = float(row["pH_insitu"])
            points.append(point)
        return points
    except Exception:
        logger.warning("Failed to load history from %s", log_file, exc_info=True)
        return []


# ── App factory ───────────────────────────────────────────────────────────────

def create_app(cfg: DictConfig, config_path: Path | None = None) -> FastAPI:
    manager = ConnectionManager()
    state = InstrumentState(cfg, manager, config_path=config_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[type-arg]
        ws_handler = WebSocketLogHandler(manager)
        ws_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        logging.getLogger().addHandler(ws_handler)
        await state.startup()
        yield
        await state.shutdown()
        logging.getLogger().removeHandler(ws_handler)

    app = FastAPI(title="phox2 Instrument GUI", lifespan=lifespan)

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/")
    async def root() -> FileResponse:
        return FileResponse(
            str(_STATIC_DIR / "index.html"),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/history")
    async def history() -> list:
        return _load_history(state.instrument_type, state._base_path)

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await manager.connect(ws)
        try:
            # Send initial state and history so the client can populate the UI
            await ws.send_text(_dumps(state.state_snapshot()))
            await ws.send_text(
                _dumps(
                    {
                        "type": "history",
                        "points": _load_history(state.instrument_type, state._base_path),
                    }
                )
            )
            # Command receive loop
            while True:
                raw = await ws.receive_text()
                msg = json.loads(raw)
                await state.handle_command(msg)
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.debug("WebSocket handler error", exc_info=True)
        finally:
            manager.disconnect(ws)

    return app
