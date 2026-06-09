from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openness_loader import load_openness, start_tia


def main() -> int:
    api_dir = load_openness()
    print(f"Loaded Openness API: {api_dir}")

    tia = start_tia(with_ui=True)
    print("TIA Portal started through Openness.")
    tia.Dispose()
    print("TIA Portal session disposed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
