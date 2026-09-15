"""Rack chain commands reach racks on return tracks and on the Master track."""

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

    class ControlSurface:  # minimal stand-in for Live's base class
        def __init__(self, *args, **kwargs):
            pass

    control_surface.ControlSurface = ControlSurface
    framework.ControlSurface = control_surface
    sys.modules.setdefault("_Framework", framework)
    sys.modules.setdefault("_Framework.ControlSurface", control_surface)
    spec = importlib.util.spec_from_file_location("ableton_mcp_remote_script", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.AbletonMCP


class _Param:
    def __init__(self, name, value=0.0, lo=0.0, hi=1.0):
        self.name, self.value, self.min, self.max = name, value, lo, hi
        self.is_quantized, self.is_enabled = False, True

    def str_for_value(self, value):
        return f"{value:.2f}"


class _Device:
    def __init__(self, name, params=(), chains=None):
        self.name = name
        self.parameters = list(params)
        self.can_have_chains = chains is not None
        self.chains = chains or []


class _Chain:
    def __init__(self, name, devices):
        self.name, self.devices = name, devices


class _Track:
    def __init__(self, devices):
        self.devices = devices


@pytest.fixture
def bridge():
    cls = _load_script_class()
    inst = object.__new__(cls)
    ott = _Device("Multiband Dynamics", [_Param("Amount", 0.5), _Param("Time", 0.3)])
    master_rack = _Device("Quick Master", chains=[_Chain("Chain 1", [ott])])
    reverb = _Device("Reverb", [_Param("Dry/Wet", 0.4)])
    return_rack = _Device("Verb Rack", chains=[_Chain("Chain 1", [reverb])])
    saturator = _Device("Saturator", [_Param("Drive", 0.0)])
    track_rack = _Device("Bass Rack", chains=[_Chain("Chain 1", [saturator])])
    inst._song = types.SimpleNamespace(
        tracks=[_Track([track_rack])],
        return_tracks=[_Track([return_rack])],
        master_track=_Track([master_rack]),
    )
    return inst


def test_master_rack_chains_and_parameters(bridge):
    chains = bridge._get_rack_chains(0, 0, "master")
    assert chains["rack"] == "Quick Master"
    assert chains["chains"][0]["devices"][0]["name"] == "Multiband Dynamics"
    params = bridge._get_chain_device_parameters(0, 0, 0, 0, "master")
    assert params["device"] == "Multiband Dynamics"
    assert [p["name"] for p in params["parameters"]] == ["Amount", "Time"]


def test_master_chain_parameter_can_be_set(bridge):
    result = bridge._set_chain_device_parameter(99, 0, 0, 0, "Amount", 0.9, "master")
    assert result == {"device": "Multiband Dynamics", "parameter": "Amount", "value": 0.9}


def test_return_and_default_track_types(bridge):
    assert bridge._get_rack_chains(0, 0, "return")["rack"] == "Verb Rack"
    assert bridge._get_rack_chains(0, 0)["rack"] == "Bass Rack"
    assert bridge._get_chain_device_parameters(0, 0, 0, 0)["device"] == "Saturator"


def test_invalid_track_type_rejected(bridge):
    with pytest.raises(ValueError):
        bridge._get_rack_chains(0, 0, "group")
    with pytest.raises(IndexError):
        bridge._get_rack_chains(3, 0, "return")


def test_dispatch_forwards_track_type(bridge):
    seen = {}
    bridge._get_rack_chains = lambda t, d, tt="track": seen.setdefault("args", (t, d, tt))
    table = type(bridge)._READONLY_COMMANDS
    table["get_rack_chains"](bridge, {"track_index": 0, "device_index": 0, "track_type": "master"})
    assert seen["args"] == (0, 0, "master")
