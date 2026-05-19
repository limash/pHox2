"""
Instrument factory (Dependency Inversion Principle).

High-level policy (InstrumentFactory) owns the wiring of concrete classes to
abstractions.  The rest of the codebase never instantiates concrete hardware
classes directly; it always receives them through this factory.
"""
from __future__ import annotations

import logging

from omegaconf import DictConfig

from phox2.components.drain import AirPressureDrain
from phox2.components.light import PWMLEDArray, RelayLightSource, RelayShutter
from phox2.components.pump import RelayStirrer, RelayWaterPump, SolenoidDyePump
from phox2.components.temperature import ADCTemperatureSensor
from phox2.components.valve import BistableValve
from phox2.hardware.interfaces import IAnalogInput, IDigitalOutput, IPWMOutput, ISpectrometer
from phox2.measurement.co3_cycle import (
    CO3Config,
    CO3MeasurementCycle,
    MeasurementConfig,
    SpectrometerAdjustConfig,
)
from phox2.measurement.ph_cycle import pHConfig, pHMeasurementCycle
from phox2.physics.co3_calculator import CO3Calculator
from phox2.physics.ph_calculator import pHCalculator

logger = logging.getLogger(__name__)


class InstrumentFactory:
    """
    Builds fully wired measurement cycles from an OmegaConf config.

    Selecting mock vs. real hardware is entirely contained here.
    """

    @classmethod
    def build_cycle(cls, cfg: DictConfig) -> CO3MeasurementCycle:
        """Return a ready-to-use CO3MeasurementCycle."""
        gpio, adc, spectrometer = cls._build_hardware(cfg)
        return cls._assemble_cycle(cfg, gpio, adc, spectrometer)

    @classmethod
    def build_ph_cycle(cls, cfg: DictConfig) -> pHMeasurementCycle:
        """Return a ready-to-use pHMeasurementCycle."""
        pwm, adc, spectrometer = cls._build_ph_hardware(cfg)
        return cls._assemble_ph_cycle(cfg, pwm, adc, spectrometer)

    # ── Hardware layer ────────────────────────────────────────────────────

    @classmethod
    def _build_hardware(
        cls, cfg: DictConfig
    ) -> tuple[IDigitalOutput, IAnalogInput, ISpectrometer]:
        if cfg.hardware.use_mock:
            logger.info("Hardware mode: MOCK (no real GPIO/ADC/spectrometer)")
            from phox2.hardware.mock.adc import MockAnalogInput
            from phox2.hardware.mock.gpio import MockDigitalOutput
            from phox2.hardware.mock.spectrometer import MockSpectrometer

            return (
                MockDigitalOutput(),
                MockAnalogInput(cfg.temperature),
                MockSpectrometer(cfg.spectrometer),
            )
        else:
            logger.info("Hardware mode: REAL")
            from phox2.hardware.real.adc import ADCDifferentialPiReader
            from phox2.hardware.real.gpio import PigpioDigitalOutput
            from phox2.hardware.real.spectrometer import SeabreezeSpectrometer

            return (
                PigpioDigitalOutput(),
                ADCDifferentialPiReader(cfg.adc),
                SeabreezeSpectrometer(cfg.spectrometer),
            )

    @classmethod
    def _build_ph_hardware(
        cls, cfg: DictConfig
    ) -> tuple[IPWMOutput, IAnalogInput, ISpectrometer]:
        if cfg.hardware.use_mock:
            logger.info("pH hardware mode: MOCK")
            from phox2.hardware.mock.adc import MockAnalogInput
            from phox2.hardware.mock.pwm import MockPWMOutput
            from phox2.hardware.mock.spectrometer import MockSpectrometer

            return (
                MockPWMOutput(),
                MockAnalogInput(cfg.temperature),
                MockSpectrometer(cfg.spectrometer),
            )
        else:
            logger.info("pH hardware mode: REAL")
            from phox2.hardware.real.adc import ADCDifferentialPiReader
            from phox2.hardware.real.pwm import PigpioPWMOutput
            from phox2.hardware.real.spectrometer import SeabreezeSpectrometer

            return (
                PigpioPWMOutput(),
                ADCDifferentialPiReader(cfg.adc),
                SeabreezeSpectrometer(cfg.spectrometer),
            )

    # ── Component + cycle assembly ────────────────────────────────────────

    @classmethod
    def _assemble_cycle(
        cls,
        cfg: DictConfig,
        gpio: IDigitalOutput,
        adc: IAnalogInput,
        spectrometer: ISpectrometer,
    ) -> CO3MeasurementCycle:
        gc = cfg.gpio
        tc = cfg.temperature

        valve = BistableValve(
            gpio=gpio,
            enable_pin=int(gc.valve_enable_pin),
            ch1_pin=int(gc.valve_ch1_pin),
            ch2_pin=int(gc.valve_ch2_pin),
            toggle_duration_s=float(gc.valve_toggle_duration_s),
        )
        water_pump = RelayWaterPump(gpio=gpio, pin=int(gc.water_pump_pin))
        dye_pump = SolenoidDyePump(gpio=gpio, pin=int(gc.dye_pump_pin))
        stirrer = RelayStirrer(gpio=gpio, pin=int(gc.stirrer_pin))
        light = RelayLightSource(gpio=gpio, pin=int(gc.light_pin))
        shutter = RelayShutter(gpio=gpio, pin=int(gc.shutter_pin))
        drain = AirPressureDrain(
            gpio=gpio,
            drain_pin=int(gc.drain_pin),
            air_pin=int(gc.air_pin),
        )
        temp_sensor = ADCTemperatureSensor(
            adc=adc,
            channel=int(cfg.adc.temperature_channel),
            coefficients=list(tc.calibration_coefficients),
            n_averages=int(tc.n_averages),
        )

        return CO3MeasurementCycle(
            spectrometer=spectrometer,
            valve=valve,
            water_pump=water_pump,
            dye_pump=dye_pump,
            stirrer=stirrer,
            light_source=light,
            shutter=shutter,
            drain=drain,
            temp_sensor=temp_sensor,
            calculator=CO3Calculator(),
            meas_cfg=MeasurementConfig.from_omegaconf(cfg.measurement),
            co3_cfg=CO3Config.from_omegaconf(cfg.co3),
            light_threshold_counts=float(cfg.spectrometer.light_threshold_counts),
            adj_cfg=SpectrometerAdjustConfig.from_omegaconf(cfg.spectrometer.autoadjust),
            integration_time_ms=float(cfg.spectrometer.integration_time_ms),
            ship_code=str(cfg.ship.code),
        )

    @classmethod
    def _assemble_ph_cycle(
        cls,
        cfg: DictConfig,
        pwm: IPWMOutput,
        adc: IAnalogInput,
        spectrometer: ISpectrometer,
    ) -> pHMeasurementCycle:
        gc = cfg.gpio
        pc = cfg.ph
        tc = cfg.temperature

        valve = BistableValve(
            gpio=pwm,  # IPWMOutput also exposes set_high/set_low
            enable_pin=int(gc.valve_enable_pin),
            ch1_pin=int(gc.valve_ch1_pin),
            ch2_pin=int(gc.valve_ch2_pin),
            toggle_duration_s=float(gc.valve_toggle_duration_s),
        )
        water_pump = RelayWaterPump(gpio=pwm, pin=int(gc.water_pump_pin))
        dye_pump = SolenoidDyePump(gpio=pwm, pin=int(gc.dye_pump_pin))
        stirrer = RelayStirrer(gpio=pwm, pin=int(gc.stirrer_pin))
        drain = AirPressureDrain(
            gpio=pwm,
            drain_pin=int(gc.drain_pin),
            air_pin=int(gc.air_pin),
        )
        led_array = PWMLEDArray(
            pwm=pwm,
            pins=list(int(p) for p in pc.led_slots),
            initial_duties=list(int(d) for d in pc.led_duties),
        )
        temp_sensor = ADCTemperatureSensor(
            adc=adc,
            channel=int(cfg.adc.temperature_channel),
            coefficients=list(tc.calibration_coefficients),
            n_averages=int(tc.n_averages),
        )

        return pHMeasurementCycle(
            spectrometer=spectrometer,
            valve=valve,
            water_pump=water_pump,
            dye_pump=dye_pump,
            stirrer=stirrer,
            led_array=led_array,
            drain=drain,
            temp_sensor=temp_sensor,
            calculator=pHCalculator(),
            meas_cfg=MeasurementConfig.from_omegaconf(cfg.measurement),
            ph_cfg=pHConfig.from_omegaconf(cfg.ph),
            light_threshold_counts=float(cfg.spectrometer.light_threshold_counts),
            adj_cfg=SpectrometerAdjustConfig.from_omegaconf(cfg.spectrometer.autoadjust),
            integration_time_ms=float(cfg.spectrometer.integration_time_ms),
            ship_code=str(cfg.ship.code),
        )

