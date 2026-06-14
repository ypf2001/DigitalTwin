from __future__ import annotations

import runpy
from pathlib import Path


def main() -> None:
    script = Path(__file__).with_name("generate_physical_connection_readable.py")
    runpy.run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    main()
