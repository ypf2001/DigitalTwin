"""Canonical SAC model locations for the stage-specific potato controllers."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent
RL_MODELS_DIR = ROOT / "rl_models"

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
    return RL_MODELS_DIR / STAGE_MODEL_RUNS[tag] / f"sac_{tag}_{suffix}"


def get_existing_stage_models(variant: str = "final") -> dict[str, str]:
    """Return existing canonical models as paths without the .zip suffix."""
    models: dict[str, str] = {}
    for tag in STAGE_MODEL_RUNS:
        path = get_stage_model_path(tag, variant=variant)
        if path.with_suffix(".zip").exists():
            models[tag] = str(path)
    return models
