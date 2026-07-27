"""Reference EC controller and pH safety-band logic for thesis V2.

The classes in this module are the executable Python reference used for
simulation, controller tuning, and PLC/HIL acceptance.  Parameters remain
placeholders until E3 identifies the physical rig.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class FOPDTModel:
    """First-order-plus-dead-time model ``K exp(-theta*s)/(tau*s+1)``."""

    gain: float
    tau_s: float
    delay_s: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.gain) or abs(self.gain) < 1e-12:
            raise ValueError("FOPDT gain must be finite and non-zero")
        if not math.isfinite(self.tau_s) or self.tau_s <= 0.0:
            raise ValueError("FOPDT time constant must be finite and positive")
        if not math.isfinite(self.delay_s) or self.delay_s < 0.0:
            raise ValueError("FOPDT delay must be finite and non-negative")


@dataclass(frozen=True)
class IMCPIParameters:
    kp: float
    ki_per_s: float
    integral_time_s: float
    lambda_s: float


def tune_imc_pi(model: FOPDTModel, lambda_s: float | None = None) -> IMCPIParameters:
    """Return conservative IMC-PI tuning for an FOPDT process.

    The implementation uses the common robust rule
    ``Kc=tau/(K*(lambda+theta))`` and ``Ti=tau+theta/2``.  A negative process
    gain therefore produces the correct reverse-acting controller sign.
    """

    lam = float(lambda_s if lambda_s is not None else max(model.tau_s, model.delay_s))
    if not math.isfinite(lam) or lam <= 0.0:
        raise ValueError("IMC lambda must be finite and positive")
    integral_time = model.tau_s + 0.5 * model.delay_s
    kp = model.tau_s / (model.gain * (lam + model.delay_s))
    return IMCPIParameters(
        kp=kp,
        ki_per_s=kp / integral_time,
        integral_time_s=integral_time,
        lambda_s=lam,
    )


@dataclass(frozen=True)
class SmithPIResult:
    output: float
    predicted_output: float
    model_output: float
    delayed_model_output: float
    error: float
    saturated: bool


class SmithPIController:
    """Discrete IMC-PI controller with a Smith predictor reference model."""

    def __init__(
        self,
        model: FOPDTModel,
        dt_s: float,
        lambda_s: float | None = None,
        output_min: float = 0.0,
        output_max: float = 100.0,
    ) -> None:
        if not math.isfinite(dt_s) or dt_s <= 0.0:
            raise ValueError("controller sample time must be finite and positive")
        if output_max <= output_min:
            raise ValueError("output_max must be greater than output_min")
        self.model = model
        self.dt_s = float(dt_s)
        self.params = tune_imc_pi(model, lambda_s=lambda_s)
        self.output_min = float(output_min)
        self.output_max = float(output_max)
        self._delay_steps = max(0, int(round(model.delay_s / self.dt_s)))
        self._delay = deque(maxlen=max(1, self._delay_steps + 1))
        self.reset()

    def reset(self, initial_output: float = 0.0, initial_input: float = 0.0) -> None:
        self._model_output = float(initial_output)
        self._integral = 0.0
        self._last_output = float(initial_input)
        self._delay.clear()
        for _ in range(max(1, self._delay_steps + 1)):
            self._delay.append(float(initial_output))

    def step(self, setpoint: float, measurement: float) -> SmithPIResult:
        delayed_model = self._delay[0]
        predicted = self._model_output + (float(measurement) - delayed_model)
        error = float(setpoint) - predicted

        candidate_integral = self._integral + error * self.dt_s
        raw = self.params.kp * error + self.params.ki_per_s * candidate_integral
        output = min(max(raw, self.output_min), self.output_max)
        saturated = abs(output - raw) > 1e-12
        if not saturated or (output >= self.output_max and error < 0.0) or (
            output <= self.output_min and error > 0.0
        ):
            self._integral = candidate_integral

        alpha = 1.0 - math.exp(-self.dt_s / self.model.tau_s)
        self._model_output += alpha * (
            self.model.gain * output - self._model_output
        )
        self._delay.append(self._model_output)
        self._last_output = output
        return SmithPIResult(
            output=output,
            predicted_output=predicted,
            model_output=self._model_output,
            delayed_model_output=delayed_model,
            error=error,
            saturated=saturated,
        )


@dataclass(frozen=True)
class PHBandResult:
    acid_duty: float
    acid_pulse: bool
    flush_requested: bool
    reject_batch: bool
    violation: float
    pulse_count: int


class PHPulseBandController:
    """Acid-only pH controller with a dead band and bounded pulses."""

    def __init__(
        self,
        lower: float = 5.8,
        upper: float = 6.5,
        hard_low: float = 5.5,
        pulse_on_s: float = 5.0,
        pulse_off_s: float = 30.0,
        maximum_pulses: int = 3,
        reset_count_on_recovery: bool = False,
    ) -> None:
        if not hard_low < lower < upper:
            raise ValueError("pH thresholds must satisfy hard_low < lower < upper")
        if pulse_on_s <= 0.0 or pulse_off_s < 0.0:
            raise ValueError("pH pulse times are invalid")
        if maximum_pulses < 1:
            raise ValueError("maximum_pulses must be positive")
        self.lower = float(lower)
        self.upper = float(upper)
        self.hard_low = float(hard_low)
        self.pulse_on_s = float(pulse_on_s)
        self.pulse_off_s = float(pulse_off_s)
        self.maximum_pulses = int(maximum_pulses)
        self.reset_count_on_recovery = bool(reset_count_on_recovery)
        self.reset()

    def reset(self) -> None:
        self.pulse_count = 0
        self._cooldown_s = 0.0

    def step(self, ph_actual: float, dt_s: float) -> PHBandResult:
        ph = float(ph_actual)
        dt = max(float(dt_s), 1e-9)
        self._cooldown_s = max(0.0, self._cooldown_s - dt)
        violation = max(self.lower - ph, ph - self.upper, 0.0)

        if ph < self.lower:
            return PHBandResult(0.0, False, True, ph < self.hard_low,
                                violation, self.pulse_count)
        if ph <= self.upper:
            if self.reset_count_on_recovery and self.pulse_count:
                self.pulse_count = 0
            return PHBandResult(0.0, False, False, False,
                                violation, self.pulse_count)
        if self.pulse_count >= self.maximum_pulses:
            return PHBandResult(0.0, False, False, True,
                                violation, self.pulse_count)
        if self._cooldown_s > 0.0:
            return PHBandResult(0.0, False, False, False,
                                violation, self.pulse_count)

        self.pulse_count += 1
        self._cooldown_s = self.pulse_on_s + self.pulse_off_s
        return PHBandResult(
            acid_duty=min(1.0, self.pulse_on_s / dt),
            acid_pulse=True,
            flush_requested=False,
            reject_batch=False,
            violation=violation,
            pulse_count=self.pulse_count,
        )


def acid_ec_feedforward(
    ec_set: float,
    acid_flow_l_min: float,
    water_flow_l_min: float,
    alpha_ds_m_per_fraction: float,
    ec_min: float = 0.0,
) -> float:
    """Reduce the fertilizer EC command by the measured acid EC contribution."""

    fraction = max(float(acid_flow_l_min), 0.0) / max(float(water_flow_l_min), 1e-9)
    compensation = fraction * max(float(alpha_ds_m_per_fraction), 0.0)
    return max(float(ec_min), float(ec_set) - compensation)
