"""Main irrigation-water pump model used by simulation and PLC HIL."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math

import numpy as np

from config_loader import load_config


@dataclass
class WaterPumpState:
    enabled: bool
    running: bool
    mode: str
    q_set_l_min: float
    q_actual_l_min: float
    pressure_set_bar: float
    pressure_actual_bar: float
    speed_percent: float
    volume_l: float
    delivered_volume_l: float
    flow_ok: bool
    volume_complete: bool
    batch_phase: str
    fertigation_active: bool
    pre_flush_volume_l: float
    fertigation_end_volume_l: float

    def to_dict(self) -> dict:
        return asdict(self)


class WaterPump:
    """First-order variable-speed main-pump model.

    Flow mode is the commissioning default. Pressure mode maps the pressure
    target to an equivalent flow through a calibrated system curve. The PLC
    remains responsible for the real VFD PID and hard safety interlocks.
    """

    VALID_MODES = {"flow", "pressure"}

    def __init__(self, q_set_l_min: float | None = None):
        cfg = load_config().water_pump()
        self.mode = str(cfg.get("mode", "flow")).lower()
        if self.mode not in self.VALID_MODES:
            raise ValueError(f"unsupported water-pump mode: {self.mode}")

        self.q_min_l_min = float(cfg.get("q_min_l_min", 0.0))
        self.q_max_l_min = float(cfg.get("q_max_l_min", 180.0))
        self.safe_flow_min_l_min = float(cfg.get("safe_flow_min_l_min", 20.0))
        self.rated_pressure_bar = float(cfg.get("rated_pressure_bar", 2.5))
        self.response_tau_min = max(float(cfg.get("response_tau_min", 0.5)), 1e-6)
        self.ramp_up_l_min_min = max(float(cfg.get("ramp_up_l_min_min", 300.0)), 0.0)
        self.ramp_down_l_min_min = max(float(cfg.get("ramp_down_l_min_min", 400.0)), 0.0)

        configured_q_set = float(cfg.get("q_set_l_min", 136.0))
        self.q_set_l_min = float(q_set_l_min if q_set_l_min is not None else configured_q_set)
        self.pressure_set_bar = float(cfg.get("pressure_set_bar", 1.8))
        self.target_volume_l = max(float(cfg.get("target_volume_l", 0.0)), 0.0)
        self.pre_flush_ratio = float(np.clip(cfg.get("pre_flush_ratio", 0.10), 0.0, 1.0))
        self.post_flush_ratio = float(np.clip(cfg.get("post_flush_ratio", 0.20), 0.0, 1.0))
        self.enabled = bool(cfg.get("enabled_on_reset", True))

        self.q_actual_l_min = 0.0
        self.pressure_actual_bar = 0.0
        self.speed_percent = 0.0
        self.volume_l = 0.0
        self.delivered_volume_l = 0.0
        self.running = False
        self.flow_ok = False
        self.volume_complete = False

    def set_command(
        self,
        enabled: bool,
        q_set_l_min: float | None = None,
        pressure_set_bar: float | None = None,
        target_volume_l: float | None = None,
        mode: str | None = None,
        pre_flush_ratio: float | None = None,
        post_flush_ratio: float | None = None,
        reset_volume: bool = False,
    ) -> None:
        if mode is not None:
            normalized_mode = str(mode).lower()
            if normalized_mode not in self.VALID_MODES:
                raise ValueError(f"unsupported water-pump mode: {normalized_mode}")
            self.mode = normalized_mode
        if q_set_l_min is not None:
            self.q_set_l_min = float(q_set_l_min)
        if pressure_set_bar is not None:
            self.pressure_set_bar = float(pressure_set_bar)
        if target_volume_l is not None:
            self.target_volume_l = max(float(target_volume_l), 0.0)
        if pre_flush_ratio is not None:
            self.pre_flush_ratio = float(np.clip(pre_flush_ratio, 0.0, 1.0))
        if post_flush_ratio is not None:
            self.post_flush_ratio = float(np.clip(post_flush_ratio, 0.0, 1.0))
        if reset_volume:
            self.volume_l = 0.0
            self.delivered_volume_l = 0.0
            self.volume_complete = False
        self.enabled = bool(enabled)

    def _batch_thresholds(self) -> tuple[float, float]:
        """Return the water-volume boundaries for a single irrigation batch."""
        pre_ratio = max(0.0, min(self.pre_flush_ratio, 1.0))
        post_ratio = max(0.0, min(self.post_flush_ratio, 1.0 - pre_ratio))
        pre_volume_l = self.target_volume_l * pre_ratio
        fertigation_end_l = self.target_volume_l * (1.0 - post_ratio)
        return pre_volume_l, max(pre_volume_l, fertigation_end_l)

    def _batch_phase(self) -> tuple[str, bool, float, float]:
        """Classify the batch from accumulated main-water volume.

        A zero target volume preserves the previous continuous/manual behavior:
        the carrier water may immediately enable fertigation after flow is proven.
        """
        pre_volume_l, fertigation_end_l = self._batch_thresholds()
        if not self.enabled:
            return "complete" if self.volume_complete else "idle", False, pre_volume_l, fertigation_end_l
        if self.volume_complete:
            return "complete", False, pre_volume_l, fertigation_end_l
        if self.target_volume_l <= 0.0:
            return "fertigating", self.flow_ok, pre_volume_l, fertigation_end_l
        if self.volume_l < pre_volume_l:
            return "pre_flush", False, pre_volume_l, fertigation_end_l
        if self.volume_l < fertigation_end_l:
            return "fertigating", self.flow_ok, pre_volume_l, fertigation_end_l
        return "post_flush", False, pre_volume_l, fertigation_end_l

    def _desired_flow(self) -> float:
        if not self.enabled or self.volume_complete:
            return 0.0
        if self.mode == "pressure":
            pressure_fraction = np.clip(
                self.pressure_set_bar / max(self.rated_pressure_bar, 1e-6),
                0.0,
                1.0,
            )
            desired = self.q_max_l_min * math.sqrt(float(pressure_fraction))
        else:
            desired = self.q_set_l_min
        if desired <= 0.0:
            return 0.0
        return float(np.clip(desired, self.q_min_l_min, self.q_max_l_min))

    def step(self, dt_min: float) -> WaterPumpState:
        dt = max(float(dt_min), 0.0)
        self.delivered_volume_l = 0.0
        desired = self._desired_flow()
        alpha = 1.0 - math.exp(-dt / self.response_tau_min) if dt > 0.0 else 0.0
        unconstrained = self.q_actual_l_min + alpha * (desired - self.q_actual_l_min)

        delta = unconstrained - self.q_actual_l_min
        if delta >= 0.0:
            delta = min(delta, self.ramp_up_l_min_min * dt)
        else:
            delta = max(delta, -self.ramp_down_l_min_min * dt)
        self.q_actual_l_min = float(np.clip(
            self.q_actual_l_min + delta,
            0.0,
            self.q_max_l_min,
        ))
        if desired <= 0.0 and self.q_actual_l_min < 1e-6:
            self.q_actual_l_min = 0.0

        flow_fraction = self.q_actual_l_min / max(self.q_max_l_min, 1e-6)
        self.pressure_actual_bar = self.rated_pressure_bar * flow_fraction * flow_fraction
        self.speed_percent = float(np.clip(flow_fraction * 100.0, 0.0, 100.0))
        self.running = self.enabled and self.q_actual_l_min > 1e-6 and not self.volume_complete
        self.flow_ok = self.running and self.q_actual_l_min >= self.safe_flow_min_l_min

        if self.running and dt > 0.0:
            requested_volume_l = self.q_actual_l_min * dt
            if self.target_volume_l > 0.0:
                remaining_volume_l = max(self.target_volume_l - self.volume_l, 0.0)
                self.delivered_volume_l = min(requested_volume_l, remaining_volume_l)
            else:
                self.delivered_volume_l = requested_volume_l
            self.volume_l += self.delivered_volume_l
        if self.target_volume_l > 0.0 and self.volume_l >= self.target_volume_l:
            self.volume_l = self.target_volume_l
            self.volume_complete = True
            self.enabled = False
            self.flow_ok = False
            self.running = False
            self.q_actual_l_min = 0.0
            self.pressure_actual_bar = 0.0
            self.speed_percent = 0.0

        return self.state()

    def state(self) -> WaterPumpState:
        batch_phase, fertigation_active, pre_flush_volume_l, fertigation_end_volume_l = self._batch_phase()
        return WaterPumpState(
            enabled=self.enabled,
            running=self.running,
            mode=self.mode,
            q_set_l_min=self.q_set_l_min,
            q_actual_l_min=self.q_actual_l_min,
            pressure_set_bar=self.pressure_set_bar,
            pressure_actual_bar=self.pressure_actual_bar,
            speed_percent=self.speed_percent,
            volume_l=self.volume_l,
            delivered_volume_l=self.delivered_volume_l,
            flow_ok=self.flow_ok,
            volume_complete=self.volume_complete,
            batch_phase=batch_phase,
            fertigation_active=fertigation_active,
            pre_flush_volume_l=pre_flush_volume_l,
            fertigation_end_volume_l=fertigation_end_volume_l,
        )

    def reset(self) -> WaterPumpState:
        cfg = load_config().water_pump()
        self.enabled = bool(cfg.get("enabled_on_reset", True))
        self.q_actual_l_min = 0.0
        self.pressure_actual_bar = 0.0
        self.speed_percent = 0.0
        self.volume_l = 0.0
        self.delivered_volume_l = 0.0
        self.running = False
        self.flow_ok = False
        self.volume_complete = False
        return self.state()
