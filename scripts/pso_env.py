"""PID-controlled digital twin environment for PSO evaluation.

Provides ``PIDControlledTwinEnv`` — a subclass of ``DigitalTwinEnv`` that
replaces the static algebraic ``SetpointToFlowController`` with a dynamic
IMC-PI Smith-predictor controller and a partial decoupler.

This allows PSO to search for the IMC parameters [lambda_EC, lambda_pH, beta]
using the full MixingTank + Pipe + Soil + Crop physics.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from digital_twin_env import DigitalTwinEnv
from crop_model import GrowthStage
from config_loader import load_config
from plc_control.imc_smith import (
    FOPDTModel,
    SmithPIController,
    tune_imc_pi,
)


@dataclass
class ControllerConfig:
    """IMC-PI controller configuration for one channel."""
    fopdt: FOPDTModel
    kp: float
    ki: float


def _build_fopdt(gain: float, tau_s: float, delay_s: float) -> FOPDTModel:
    """Build a FOPDT model, handling sign and validation."""
    return FOPDTModel(gain=float(gain), tau_s=float(tau_s), delay_s=float(delay_s))


def apply_decoupling(
    q_f_raw: float,
    q_a_raw: float,
    G: tuple[float, float, float, float],
    beta: float,
) -> tuple[float, float]:
    """Partial static decoupling (beta-weighted).

    .. math::
        q_f = q_f_raw - beta * (G_EC_A / G_pH_A) * q_a_raw
        q_a = q_a_raw - beta * (G_pH_F / G_EC_F) * q_f_raw

    All outputs are clamped to zero (no negative pump commands).
    """
    if beta <= 0.0:
        return float(q_f_raw), float(q_a_raw)

    g_ec_f, g_ec_a, g_ph_f, g_ph_a = G
    q_f = q_f_raw - beta * (g_ec_a / g_ph_a) * q_a_raw
    q_a = q_a_raw - beta * (g_ph_f / g_ec_f) * q_f_raw
    return max(0.0, float(q_f)), max(0.0, float(q_a))


class PIDControlledTwinEnv(DigitalTwinEnv):
    """Digital twin with IMC-PI Smith controller instead of static flow inversion.

    Parameters
    ----------
    lambda_ec_s : float
        IMC tuning parameter for the EC loop (seconds).
    lambda_ph_s : float
        IMC tuning parameter for the pH loop (seconds).
    beta : float
        Partial decoupling weight in [0, 0.5].
    gain_point : dict
        A single working-point dict from gain_schedule.yaml, containing keys
        ``gains``, ``delay_s``, ``tau_s``, ``ec``, ``ph``, ``q_f``, ``q_a``.
    """

    def __init__(
        self,
        lambda_ec_s: float,
        lambda_ph_s: float,
        beta: float,
        gain_point: dict,
        *,
        growth_stage: GrowthStage = GrowthStage.BULKING,
        area_ha: float | None = None,
        dt_min: float | None = None,
        ep_len_days: float = 2.0,
        et0_mm_day: float | None = None,
        obs_noise_std: float = 0.0,
        q_w: float | None = None,
        seed: int | None = None,
        soil_model: str | None = None,
    ):
        super().__init__(
            growth_stage=growth_stage,
            area_ha=area_ha,
            dt_min=dt_min,
            ep_len_days=ep_len_days,
            et0_mm_day=et0_mm_day,
            obs_noise_std=obs_noise_std,
            q_w=q_w,
            seed=seed,
            soil_model=soil_model,
            domain_randomization=False,
        )

        self.lambda_ec_s = float(lambda_ec_s)
        self.lambda_ph_s = float(lambda_ph_s)
        self.beta = float(beta)

        # Extract gains from the working point
        gains = gain_point["gains"]
        self._g_ec_f = float(gains["g_ec_f"])
        self._g_ec_a = float(gains["g_ec_a"])
        self._g_ph_f = float(gains["g_ph_f"])
        self._g_ph_a = float(gains["g_ph_a"])
        self._G = (self._g_ec_f, self._g_ec_a, self._g_ph_f, self._g_ph_a)

        delay_s = float(gain_point.get("delay_s", 185.0))
        tau_s = float(gain_point.get("tau_s", 375.0))

        # Build FOPDT models for EC and pH channels
        ec_model = _build_fopdt(self._g_ec_f, tau_s, delay_s)
        ph_model = _build_fopdt(self._g_ph_a, tau_s, delay_s)

        # IMC-PI tuning
        ec_params = tune_imc_pi(ec_model, lambda_s=self.lambda_ec_s)
        ph_params = tune_imc_pi(ph_model, lambda_s=self.lambda_ph_s)

        self.ec_controller_config = ControllerConfig(
            fopdt=ec_model, kp=ec_params.kp, ki=ec_params.ki_per_s
        )
        self.ph_controller_config = ControllerConfig(
            fopdt=ph_model, kp=ph_params.kp, ki=ph_params.ki_per_s
        )

        # Flow limits from config
        action_cfg = load_config().action()
        self._q_f_max = float(action_cfg.get("q_f_max", 10.0))
        self._q_a_max = float(action_cfg.get("q_a_max", 4.0))

        # Controllers (created in _build_controllers, called by reset)
        self.ec_controller: SmithPIController | None = None
        self.ph_controller: SmithPIController | None = None
        self._previous_q_f = 0.0
        self._previous_q_a = 0.0

    def _build_controllers(self):
        """Create fresh controller instances (called before each episode)."""
        dt_s = self.dt_min * 60.0  # convert minutes to seconds
        ec_model = self.ec_controller_config.fopdt
        ph_model = self.ph_controller_config.fopdt

        self.ec_controller = SmithPIController(
            model=ec_model,
            dt_s=dt_s,
            lambda_s=self.lambda_ec_s,
            output_min=0.0,
            output_max=self._q_f_max,
        )
        self.ph_controller = SmithPIController(
            model=ph_model,
            dt_s=dt_s,
            lambda_s=self.lambda_ph_s,
            output_min=0.0,
            output_max=self._q_a_max,
        )

    def reset(self):
        obs = super().reset()
        self._build_controllers()
        self._previous_q_f = 0.0
        self._previous_q_a = 0.0
        return obs

    def _setpoint_to_flow(self, action):
        """Override: use Smith-PI + decoupler instead of static algebraic inversion.

        Mirrors the parent logic for night-time gating, pump state, pH band, etc.,
        but replaces ``SetpointToFlowController.to_flow()`` with closed-loop PID.
        """
        # ---- 1. Compute EC/pH setpoints (same as parent) ----
        stage_ec = self.crop.get_target_ec(self.control_stage)
        projected = self.action_projector.project(action, stage_ec=stage_ec)
        self.water_pump.q_set_l_min = self._base_q_w * projected.water_multiplier
        pump_state = self.water_pump.step(self.dt_min)
        q_w_actual = pump_state.q_actual_l_min

        ec_set = projected.ec_set
        ph_nominal = projected.ph_nominal

        # ---- 2. pH pulse-band controller (same as parent) ----
        is_night = self._is_nighttime(self._time_min)
        if self._previous_nighttime and not is_night:
            self.ph_band_controller.reset()
        self._previous_nighttime = is_night

        ph_feedback = float(self.pipe.ph_filt)
        dt_s = self.dt_min * 60.0
        ph_band = self.ph_band_controller.step(ph_feedback, dt_s)

        # ---- 3. EC Smith-PI closed loop (replaces static _solve_q_f) ----
        ec_feedback = float(self.pipe.ec_filt)
        ec_result = self.ec_controller.step(ec_set, ec_feedback)
        q_f_raw = ec_result.output

        # ---- 4. pH Smith-PI closed loop (replaces static _solve_q_a) ----
        ph_result = self.ph_controller.step(ph_nominal, ph_feedback)
        q_a_raw = (
            ph_result.output * (1.0 if ph_band.acid_pulse else ph_band.acid_duty)
        )

        # ---- 5. Partial decoupling ----
        q_f, q_a = apply_decoupling(q_f_raw, q_a_raw, self._G, self.beta)

        # ---- 6. Apply the same night/flow/pH gates as parent ----
        if (
            is_night
            or not pump_state.flow_ok
            or not pump_state.fertigation_active
            or ph_band.flush_requested
            or ph_band.reject_batch
        ):
            q_f = 0.0
            q_a = 0.0

        self._previous_q_f = float(q_f)
        self._previous_q_a = float(q_a)

        # ---- 7. Irrigation accounting (same as parent) ----
        delivered_water_l = pump_state.delivered_volume_l
        if self.dt_min > 0.0:
            carrier_irrigation_mm_h = delivered_water_l * 60.0 / (
                self.dt_min * self.area_ha * 10000.0
            )
        else:
            carrier_irrigation_mm_h = 0.0
        dosing_irrigation_mm_h = (q_f + q_a) * 60.0 / (self.area_ha * 10000.0)
        irrigation_mm_h = carrier_irrigation_mm_h + dosing_irrigation_mm_h

        return (
            ec_set,
            ph_nominal,
            q_f,
            q_a,
            q_w_actual,
            irrigation_mm_h,
            carrier_irrigation_mm_h,
            pump_state,
            projected,
            ph_band,
        )
