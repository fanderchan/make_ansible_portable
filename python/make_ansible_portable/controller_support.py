from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTROL_NODE_SUPPORT_FILE = PROJECT_ROOT / "data" / "ansible_control_node_python.json"


@dataclass(frozen=True)
class ControllerPythonSupport:
    minor: str
    package_name: str
    minimum_python3: str
    display: str
    official_text: str
    source_url: str
    source_note: str
    note: str = ""
    note_source_url: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "minor": self.minor,
            "package_name": self.package_name,
            "minimum_python3": self.minimum_python3,
            "display": self.display,
            "official_text": self.official_text,
            "source_url": self.source_url,
            "source_note": self.source_note,
            "note": self.note,
            "note_source_url": self.note_source_url,
        }


def _minor_from_version(version: str) -> str:
    parts = version.split(".")
    if len(parts) < 2:
        return version
    return ".".join(parts[:2])


@lru_cache(maxsize=1)
def load_controller_support_map() -> dict[str, ControllerPythonSupport]:
    payload = json.loads(CONTROL_NODE_SUPPORT_FILE.read_text(encoding="utf-8"))
    result: dict[str, ControllerPythonSupport] = {}
    for entry in payload.get("entries", []):
        support = ControllerPythonSupport(
            minor=str(entry["minor"]),
            package_name=str(entry["package_name"]),
            minimum_python3=str(entry["minimum_python3"]),
            display=str(entry["display"]),
            official_text=str(entry["official_text"]),
            source_url=str(entry["source_url"]),
            source_note=str(entry["source_note"]),
            note=str(entry.get("note") or ""),
            note_source_url=str(entry.get("note_source_url") or ""),
        )
        result[support.minor] = support
    return result


def lookup_controller_support(package_name: str, version: str) -> ControllerPythonSupport | None:
    support = load_controller_support_map().get(_minor_from_version(version))
    if support is None:
        return None
    if support.package_name != package_name:
        return None
    return support

