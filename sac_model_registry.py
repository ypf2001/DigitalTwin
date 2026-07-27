"""Canonical SAC model locations.

The four 2026-06 runs are legacy ``[EC_set, pH_set]`` baselines and are not
returned for V2 inference. The V2 production candidate is one stage-aware
``[water_multiplier, EC_residual]`` policy.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent
RL_MODELS_DIR = ROOT / "rl_models"
RESIDUAL_MODEL_PATH = RL_MODELS_DIR / "sac_residual_all_final"

STAGE_MODEL_RUNS = {
    "ini": "ini_20260614_231157",
    "dev": "dev_20260614_234632",
    "mid": "mid_20260615_003559",
    "late": "late_20260615_005859",
}


def normalize_stage_tag(stage: str) -> str:
    """Return the project SAC stage tag for user-facing stage names."""
    tag = str(stage or "mid").strip().lower()
    aliases = {
        "emergence": "ini",
        "vegetative": "dev",
        "tuber_init": "dev",
        "bulking": "mid",
        "starch_accumulation": "late",
        "maturation": "late",
    }
    return aliases.get(tag, tag)


def get_stage_model_path(stage: str, variant: str = "final") -> Path:
    """Return the canonical model path without the .zip suffix."""
    tag = normalize_stage_tag(stage)
    if tag not in STAGE_MODEL_RUNS:
        raise KeyError(f"Unknown SAC stage tag: {stage}")
    suffix = "best_model" if variant == "best" else "final"
    residual = RL_MODELS_DIR / f"sac_residual_{tag}_{suffix}"
    if residual.with_suffix(".zip").exists() or not (RL_MODELS_DIR / STAGE_MODEL_RUNS[tag]).exists():
        return residual
    return RL_MODELS_DIR / STAGE_MODEL_RUNS[tag] / f"sac_{tag}_{suffix}"


def get_existing_stage_models(variant: str = "final") -> dict[str, str]:
    """Return only a compatible stage-aware residual model, if present."""
    if RESIDUAL_MODEL_PATH.with_suffix(".zip").exists():
        return {tag: str(RESIDUAL_MODEL_PATH) for tag in STAGE_MODEL_RUNS}
    found: dict[str, str] = {}
    suffix = "best_model" if variant == "best" else "final"
    for tag, run_name in STAGE_MODEL_RUNS.items():
        residual = RL_MODELS_DIR / f"sac_residual_{tag}_{suffix}"
        legacy = RL_MODELS_DIR / run_name / f"sac_{tag}_{suffix}"
        if residual.with_suffix(".zip").exists():
            found[tag] = str(residual)
        elif legacy.with_suffix(".zip").exists():
            found[tag] = str(legacy)
    return found
