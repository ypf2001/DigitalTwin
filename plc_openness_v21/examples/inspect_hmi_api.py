from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openness_loader import load_openness, start_tia
from plc_programming import attach_to_open_project, iter_device_items, open_project


PROJECT_PATH = Path(r"D:\dw_plc\xiaweiji\xiaweiji.ap21")
OUT = ROOT / "generated_hmi" / "inspect_hmi_api.log"


def log(msg: str) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


def find_hmi(project):
    from Siemens.Engineering.HW.Features import SoftwareContainer  # type: ignore

    for device in project.Devices:
        for item in iter_device_items(device):
            try:
                container = item.GetService[SoftwareContainer]()
            except Exception:
                container = None
            if container is not None and container.Software is not None:
                sw = container.Software
                if str(sw.Name).startswith("HMI_RT_"):
                    return sw
    raise RuntimeError("HMI runtime not found")


def dump_attrs(obj, title: str) -> None:
    log(f"\n== {title} ==")
    try:
        for info in obj.GetAttributeInfos():
            try:
                value = obj.GetAttribute(info.Name)
            except Exception as exc:
                value = f"<ERR {exc}>"
            log(f"ATTR {info.Name} type={getattr(info, 'Type', '')} access={getattr(info, 'AccessMode', '')} value={value}")
    except Exception:
        log("ATTRS FAILED")
        log(traceback.format_exc())
    try:
        for info in obj.GetCompositionInfos():
            log(f"COMP {info.Name} type={getattr(info, 'Type', '')}")
    except Exception:
        pass
    try:
        for info in obj.GetCreationInfos("Connections"):
            log(f"CREATE Connections {info}")
    except Exception as exc:
        log(f"CREATE Connections failed: {exc}")


def main() -> int:
    if OUT.exists():
        OUT.unlink()
    load_openness()
    tia, project = attach_to_open_project(PROJECT_PATH)
    attached = project is not None
    if tia is None:
        tia = start_tia(with_ui=True)
    try:
        if project is None:
            project = open_project(tia, PROJECT_PATH)
        log(f"Project={project.Name}")
        hmi = find_hmi(project)
        log(f"HMI={hmi.Name} type={type(hmi)}")
        dump_attrs(hmi, "HMI software")
        try:
            log(f"Connections count={hmi.Connections.Count}")
            dump_attrs(hmi.Connections, "HMI connections composition")
            for conn in hmi.Connections:
                dump_attrs(conn, f"Connection {conn.Name}")
        except Exception:
            log("Connections inspect failed")
            log(traceback.format_exc())
        try:
            table = hmi.TagFolder.DefaultTagTable
            dump_attrs(table, f"Default tag table {table.Name}")
            for tag in table.Tags:
                dump_attrs(tag, f"Tag {tag.Name}")
        except Exception:
            log("Tag inspect failed")
            log(traceback.format_exc())
        return 0
    except BaseException:
        log("FAILED")
        log(traceback.format_exc())
        raise
    finally:
        if project is not None and not attached:
            project.Close()
        tia.Dispose()


if __name__ == "__main__":
    raise SystemExit(main())
