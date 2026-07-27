"""Configurable 2x2 FOPDT process used by E3/E4 HIL experiments."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class MIMOFOPDTParameters:
    g_ec_f: float
    g_ec_a: float
    g_ph_f: float
    g_ph_a: float
    delay_s: float
    tau_ec_s: float
    tau_ph_s: float

    def validate(self) -> None:
        values = (
            self.g_ec_f, self.g_ec_a, self.g_ph_f, self.g_ph_a,
            self.delay_s, self.tau_ec_s, self.tau_ph_s,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("MIMO FOPDT parameters must be finite")
        if self.delay_s < 0.0 or self.tau_ec_s <= 0.0 or self.tau_ph_s <= 0.0:
            raise ValueError("delay must be non-negative and time constants positive")


class MIMOFOPDTPlant:
    """Two-input, two-output delayed first-order process in engineering units."""

    def __init__(self, parameters: MIMOFOPDTParameters, dt_s: float):
        parameters.validate()
        if not math.isfinite(dt_s) or dt_s <= 0.0:
            raise ValueError("dt_s must be positive")
        self.parameters = parameters
        self.dt_s = float(dt_s)
        self._delay_samples = max(0, int(round(parameters.delay_s / self.dt_s)))
        self._input_history: deque[tuple[float, float]] = deque()
        self.reset(0.0, 0.0, 0.0, 7.0)

    def reset(self, q_f: float, q_a: float, ec: float, ph: float) -> None:
        self.q_f_baseline = float(q_f)
        self.q_a_baseline = float(q_a)
        self.ec_baseline = float(ec)
        self.ph_baseline = float(ph)
        self._ec_delta = 0.0
        self._ph_delta = 0.0
        self._input_history.clear()
        for _ in range(self._delay_samples):
            self._input_history.append((self.q_f_baseline, self.q_a_baseline))

    def step(self, q_f: float, q_a: float) -> tuple[float, float]:
        self._input_history.append((float(q_f), float(q_a)))
        delayed_q_f, delayed_q_a = self._input_history.popleft()
        p = self.parameters
        delta_f = delayed_q_f - self.q_f_baseline
        delta_a = delayed_q_a - self.q_a_baseline
        ec_target = p.g_ec_f * delta_f + p.g_ec_a * delta_a
        ph_target = p.g_ph_f * delta_f + p.g_ph_a * delta_a
        alpha_ec = min(1.0, self.dt_s / p.tau_ec_s)
        alpha_ph = min(1.0, self.dt_s / p.tau_ph_s)
        self._ec_delta += alpha_ec * (ec_target - self._ec_delta)
        self._ph_delta += alpha_ph * (ph_target - self._ph_delta)
        return self.ec_baseline + self._ec_delta, self.ph_baseline + self._ph_delta

    def inject_output(self, *, ec_delta: float = 0.0, ph_delta: float = 0.0) -> tuple[float, float]:
        """Apply a reproducible output disturbance for guarded HIL tests."""
        if not math.isfinite(ec_delta) or not math.isfinite(ph_delta):
            raise ValueError("output disturbance must be finite")
        self._ec_delta += float(ec_delta)
        self._ph_delta += float(ph_delta)
        return self.ec_baseline + self._ec_delta, self.ph_baseline + self._ph_delta
