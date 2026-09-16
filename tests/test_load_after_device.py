"""Loading a browser item after a chosen device selects that device first and reports the index."""

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
    spec = importlib.util.spec_from_file_location("ableton_mcp_remote_script_load", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.AbletonMCP


class _Device:
    def __init__(self, name):
        self.name = name


class _Item:
    def __init__(self, name):
        self.name, self.uri = name, "query:AudioFx#" + name


class _Browser:
    """Mimics Live: a loaded audio effect lands right after the selected device."""

    def __init__(self, song):
        self.song = song

    def load_item(self, item):
        track = self.song.view.selected_track
        sel = self.song.view.selected_device
        pos = track.devices.index(sel) + 1 if sel in track.devices else len(track.devices)
        track.devices.insert(pos, _Device(item.name))


class _View:
    def __init__(self):
        self.selected_track = None
        self.selected_device = None

    def select_device(self, device):
        self.selected_device = device


@pytest.fixture
def bridge():
    cls = _load_script_class()
    inst = object.__new__(cls)
    track = types.SimpleNamespace(
        name="MID BASS",
        devices=[_Device("Wavetable"), _Device("Erosion"), _Device("EQ Eight")],
    )
    song = types.SimpleNamespace(tracks=[track], return_tracks=[], master_track=track)
    song.view = _View()
    inst._song = song
    item = _Item("Utility")
    app = types.SimpleNamespace(browser=_Browser(song))
    inst.application = lambda: app
    inst._find_browser_item_by_uri = lambda browser, uri: item if uri == item.uri else None
    inst.log_message = lambda *a, **k: None
    return inst, track, item


def test_insert_after_device_lands_at_next_index(bridge):
    inst, track, item = bridge
    r = inst._load_browser_item(0, item.uri, after_device_index=0)
    assert [d.name for d in track.devices] == ["Wavetable", "Utility", "Erosion", "EQ Eight"]
    assert r["device_index"] == 1


def test_default_appends_after_last_device(bridge):
    inst, track, item = bridge
    r = inst._load_browser_item(0, item.uri)
    assert [d.name for d in track.devices][-1] == "Utility"
    assert r["device_index"] == 3


def test_out_of_range_anchor_rejected(bridge):
    inst, track, item = bridge
    with pytest.raises(IndexError):
        inst._load_browser_item(0, item.uri, after_device_index=7)


def test_inserted_index_helper():
    cls = _load_script_class()
    assert cls._inserted_index(["a", "b"], ["a", "x", "b"]) == 1
    assert cls._inserted_index(["a", "b"], ["a", "b", "x"]) == 2
    assert cls._inserted_index(["a", "b"], ["y", "b"]) == 0  # replaced (instrument slot)
    assert cls._inserted_index(["a"], ["a"]) is None
