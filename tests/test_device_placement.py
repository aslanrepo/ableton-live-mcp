"""insert_device / move_device / replace_device against stub Live objects (Live 12.3 API)."""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT_PATH = ROOT / "ableton_live_mcp" / "remote_script" / "__init__.py"


def _load_script_class():
    framework = types.ModuleType("_Framework")
    control_surface = types.ModuleType("_Framework.ControlSurface")

    class ControlSurface:
        def __init__(self, *args, **kwargs):
            pass

    control_surface.ControlSurface = ControlSurface
    framework.ControlSurface = control_surface
    sys.modules.setdefault("_Framework", framework)
    sys.modules.setdefault("_Framework.ControlSurface", control_surface)
    spec = importlib.util.spec_from_file_location("ableton_mcp_remote_script_place", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.AbletonMCP


class _Param:
    def __init__(self, name, value=0.0, lo=0.0, hi=1.0):
        self.name, self.value, self.min, self.max = name, value, lo, hi
        self.is_enabled = True


CATALOG = {
    "Utility": lambda: _Device("Utility", [_Param("Gain", 0.5, -1, 1)]),
    "Erosion": lambda: _Device(
        "Erosion", [_Param("Frequency", 0.1), _Param("Amount", 0.0), _Param("Noise Blend", 0.5)]
    ),
}


class _Device:
    def __init__(self, name, params=()):
        self.name = name
        self.parameters = list(params)


class _Chain:
    """Stub with the Live 12.3 track/chain API used by the bridge."""

    def __init__(self, name, devices):
        self.name, self.devices = name, devices

    def delete_device(self, index):
        del self.devices[index]

    def insert_device(self, name, index=None):
        dev = CATALOG[name]()
        self.devices.insert(len(self.devices) if index is None else index, dev)


class _Song:
    def move_device(self, device, container, position):
        # Live semantics: position counted with the device still present.
        devices = container.devices
        old = devices.index(device)
        devices.insert(position, device)
        del devices[old if old < position else old + 1]


@pytest.fixture
def bridge():
    cls = _load_script_class()
    inst = object.__new__(cls)
    legacy = _Device(
        "Erosion Legacy",
        [_Param("Mode", 2.0, 0, 2), _Param("Frequency", 0.7), _Param("Amount", 0.3)],
    )
    track = _Chain(
        "MID BASS", [_Device("Wavetable"), legacy, _Device("Overdrive"), _Device("EQ Eight")]
    )
    inst._song = types.SimpleNamespace(
        tracks=[track],
        return_tracks=[],
        master_track=_Chain("Master", []),
        move_device=_Song().move_device,
    )
    return inst, track


def test_insert_at_index_and_at_end(bridge):
    inst, track = bridge
    r = inst._insert_device(0, "Utility", 1)
    assert [d.name for d in track.devices][:2] == ["Wavetable", "Utility"]
    assert r["device_index"] == 1 and r["device_count"] == 5
    r = inst._insert_device(0, "Utility")
    assert track.devices[-1].name == "Utility" and r["device_index"] == 5


def test_move_right_and_left_final_positions(bridge):
    inst, track = bridge
    r = inst._move_device(0, 1, 3)  # Erosion Legacy to the end
    assert r["order"] == ["Wavetable", "Overdrive", "EQ Eight", "Erosion Legacy"]
    assert r["device_index"] == 3
    r = inst._move_device(0, 3, 1)  # and back
    assert r["order"] == ["Wavetable", "Erosion Legacy", "Overdrive", "EQ Eight"]
    assert r["device_index"] == 1


def test_replace_keeps_position_and_reports_uncopied(bridge):
    inst, track = bridge
    r = inst._replace_device(0, 1, "Erosion")
    assert [d.name for d in track.devices] == ["Wavetable", "Erosion", "Overdrive", "EQ Eight"]
    assert r["replaced"] == "Erosion Legacy" and r["with"] == "Erosion" and r["device_index"] == 1
    assert r["copied"] == ["Frequency", "Amount"]
    assert r["not_copied"] == ["Mode"]
    new = track.devices[1]
    assert {p.name: p.value for p in new.parameters}["Frequency"] == 0.7


def test_replace_clamps_and_rejects_bad_index(bridge):
    inst, track = bridge
    track.devices[1].parameters[1].value = 5.0  # Frequency beyond the new device's max 1.0
    inst._replace_device(0, 1, "Erosion")
    assert {p.name: p.value for p in track.devices[1].parameters}["Frequency"] == 1.0
    with pytest.raises(IndexError):
        inst._replace_device(0, 9, "Erosion")


def test_container_resolution_and_master_delete(bridge):
    inst, track = bridge
    inst._song.master_track.devices.append(_Device("Limiter"))
    r = inst._delete_device(0, 0, "master")
    assert r["device_count"] == 0 and r["track"] == "Master"
    with pytest.raises(ValueError):
        inst._resolve_container(0, "track", rack_device_index=0)
