"""Device loading and parameter control, incl. Master/Return chains."""

import json

from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

from ..app import mcp
from ..connection import get_ableton_connection
from ._util import (
    AfterDeviceIndex,
    BrowserItemUri,
    ChainIndex,
    DeviceIndex,
    DeviceParameter,
    DeviceParameterValue,
    RackDeviceIndex,
    RackTrackType,
    ReturnIndex,
    ToggleState,
    TrackIndex,
    params,
)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False))
def load_instrument_or_effect(
    ctx: Context, track_index: int, uri: str, after_device_index: AfterDeviceIndex = None
) -> str:
    """
    Load an instrument or effect onto a track using its URI.

    Parameters:
    - track_index: The index of the track to load the instrument on
    - uri: The URI of the instrument or effect to load (e.g., 'query:Synths#Instrument%20Rack:Bass:FileId_5116')
    - after_device_index: insert right after this device in the track's chain
      (omit to append at the end). Live keeps instruments in the instrument slot
      regardless. The reply names the index the new device landed at.
    """
    wire = {"track_index": track_index, "item_uri": uri}
    if after_device_index is not None:
        wire["after_device_index"] = after_device_index
    result = get_ableton_connection().send_command("load_browser_item", wire)
    # The Remote Script raises on failure, so a reply means it loaded.
    where = result.get("device_index")
    at = f" at device index {where}" if where is not None else ""
    return f"Loaded '{result.get('item_name', uri)}' on track '{result.get('track_name', track_index)}'{at}"


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def get_device_parameters(ctx: Context, track_index: int, device_index: int) -> str:
    """List all parameters of a device on a track: names, values, ranges, display strings."""
    result = get_ableton_connection().send_command(
        "get_device_parameters", {"track_index": track_index, "device_index": device_index}
    )
    return json.dumps(result, indent=2)


def _set_param(command: str, prefix: str, **wire_params) -> str:
    r = get_ableton_connection().send_command(command, wire_params)
    result = f"{prefix}{r.get('device')}: {r.get('parameter')} = {r.get('display', r.get('value'))}"
    if r.get("warning"):
        result += f" (Warning: {r['warning']})"
    return result


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False))
def set_device_parameter(
    ctx: Context,
    track_index: TrackIndex,
    device_index: DeviceIndex,
    parameter: DeviceParameter,
    value: DeviceParameterValue,
) -> str:
    """Set a parameter after reading get_device_parameters. Numbers use the native range;
    strings use display units ('250 Hz', '-6 dB') or exact enum labels. Unsupported
    display mappings fail before writing. Returns Live's actual readback and warnings."""
    return _set_param(
        "set_device_parameter",
        "",
        track_index=track_index,
        device_index=device_index,
        parameter=parameter,
        value=value,
    )


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=True))
def set_device_enabled(
    ctx: Context,
    track_index: TrackIndex,
    device_index: DeviceIndex,
    enabled: ToggleState,
) -> str:
    """Enable or bypass one device on a regular track.

    `true` turns the device on; `false` bypasses its processing while preserving
    the device and parameter values. This changes audible signal flow but not
    clip content. Use set_track_mute to silence the whole track, or
    set_device_parameter to change one control.
    """
    r = get_ableton_connection().send_command(
        "set_device_enabled",
        {"track_index": track_index, "device_index": device_index, "enabled": enabled},
    )
    return f"{r.get('device')} enabled={r.get('enabled')}"


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=False))
def load_device_to_return(
    ctx: Context,
    return_index: ReturnIndex,
    item_uri: BrowserItemUri,
    after_device_index: AfterDeviceIndex = None,
) -> str:
    """Append one loadable browser device or preset to a return track's chain
    (or insert it right after `after_device_index`).

    Obtain `item_uri` from search_browser. Loading selects the return track in
    Live and creates a new device, so repeated calls add duplicates. Prefer audio
    effects on returns; use load_instrument_or_effect for a regular track or
    load_device_to_master for the Master chain.
    """
    wire = {"return_index": return_index, "item_uri": item_uri}
    if after_device_index is not None:
        wire["after_device_index"] = after_device_index
    r = get_ableton_connection().send_command("load_device_to_return", wire)
    where = r.get("device_index")
    at = f" at device index {where}" if where is not None else ""
    return f"Loaded {r.get('item_name')} onto return {return_index}{at}"


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False))
def load_device_to_master(
    ctx: Context, item_uri: str, after_device_index: AfterDeviceIndex = None
) -> str:
    """Load a device/effect from the browser onto the Master/Main track (e.g. a
    limiter for mastering), appended or inserted right after `after_device_index`."""
    wire = {"item_uri": item_uri}
    if after_device_index is not None:
        wire["after_device_index"] = after_device_index
    r = get_ableton_connection().send_command("load_device_to_master", wire)
    where = r.get("device_index")
    at = f" at device index {where}" if where is not None else ""
    return f"Loaded {r.get('item_name')} onto master{at}"


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def get_master_device_parameters(ctx: Context, device_index: int) -> str:
    """List parameters of a device on the Master track."""
    return json.dumps(
        get_ableton_connection().send_command(
            "get_master_device_parameters", {"device_index": device_index}
        ),
        indent=2,
    )


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=True))
def set_master_device_parameter(
    ctx: Context,
    device_index: DeviceIndex,
    parameter: DeviceParameter,
    value: DeviceParameterValue,
) -> str:
    """Set one enabled parameter on a device in the Master track's chain.

    Call get_master_device_parameters first and use its parameter name/index and
    native min/max; numeric out-of-range values are clamped. Display strings with
    supported units or exact enum labels also work; unsupported mappings fail
    before writing. This affects the full mix. Read back the resulting display.
    Use set_device_parameter for a regular track or
    set_return_device_parameter for a return track.
    """
    return _set_param(
        "set_master_device_parameter",
        "master ",
        device_index=device_index,
        parameter=parameter,
        value=value,
    )


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=True))
def set_return_device_parameter(
    ctx: Context,
    return_index: ReturnIndex,
    device_index: DeviceIndex,
    parameter: DeviceParameter,
    value: DeviceParameterValue,
) -> str:
    """Set one enabled parameter on a device in a return track's chain.

    Call get_return_device_parameters first and use its parameter name/index and
    native min/max; numeric out-of-range values are clamped. Supported display-unit
    strings and exact enum labels also work; unsupported mappings fail before writing.
    Use set_device_parameter for
    a regular track or set_master_device_parameter for the full-mix chain.
    """
    return _set_param(
        "set_return_device_parameter",
        f"return {return_index} ",
        return_index=return_index,
        device_index=device_index,
        parameter=parameter,
        value=value,
    )


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def get_return_device_parameters(ctx: Context, return_index: int, device_index: int) -> str:
    """List parameters of a device on a Return track: names, values, min/max,
    display strings. Call before set_return_device_parameter."""
    result = get_ableton_connection().send_command(
        "get_return_device_parameters",
        {"return_index": return_index, "device_index": device_index},
    )
    return json.dumps(result, indent=2)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def get_rack_chains(
    ctx: Context, track_index: int, device_index: int, track_type: RackTrackType = "track"
) -> str:
    """List an Instrument/Effect Rack's chains and the devices inside each -
    previously unreachable nested devices. Use get_chain_device_parameters to
    read them and set_chain_device_parameter to control them. Racks on a return
    track or on the Master track are reached with track_type='return' /
    'master' (for 'master' track_index is ignored; pass 0)."""

    r = get_ableton_connection().send_command(
        "get_rack_chains",
        {"track_index": track_index, "device_index": device_index, "track_type": track_type},
    )
    return json.dumps(r, indent=2)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def get_chain_device_parameters(
    ctx: Context,
    track_index: int,
    device_index: int,
    chain_index: int,
    chain_device_index: int,
    track_type: RackTrackType = "track",
) -> str:
    """List all parameters of a device INSIDE a rack chain (indices from
    get_rack_chains): names, native values, min/max, display strings, and
    value_items for switches. Same payload as get_device_parameters. Call
    before set_chain_device_parameter. Use the same track_type you gave
    get_rack_chains ('track', 'return' or 'master')."""
    r = get_ableton_connection().send_command(
        "get_chain_device_parameters",
        {
            "track_index": track_index,
            "device_index": device_index,
            "chain_index": chain_index,
            "chain_device_index": chain_device_index,
            "track_type": track_type,
        },
    )
    return json.dumps(r, indent=2)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False))
def set_chain_device_parameter(
    ctx: Context,
    track_index: int,
    device_index: int,
    chain_index: int,
    chain_device_index: int,
    parameter: str | int,
    value: float,
    track_type: RackTrackType = "track",
) -> str:
    """Set a parameter on a device INSIDE a rack chain (indices from
    get_rack_chains). Values clamp to the parameter's native range. Use the
    same track_type you gave get_rack_chains ('track', 'return' or 'master')."""
    return _set_param(
        "set_chain_device_parameter",
        "",
        track_index=track_index,
        device_index=device_index,
        chain_index=chain_index,
        chain_device_index=chain_device_index,
        parameter=parameter,
        value=value,
        track_type=track_type,
    )


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def get_drum_pads(ctx: Context, track_index: int, device_index: int) -> str:
    """List a Drum Rack's occupied pads (MIDI note, name, mute, solo)."""

    r = get_ableton_connection().send_command(
        "get_drum_pads", {"track_index": track_index, "device_index": device_index}
    )
    return json.dumps(r, indent=2)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False))
def set_drum_pad(
    ctx: Context,
    track_index: int,
    device_index: int,
    note: int,
    mute: bool | None = None,
    solo: bool | None = None,
    name: str | None = None,
) -> str:
    """Mute/solo/rename a single Drum Rack pad by its MIDI note (e.g. 36=kick).
    Per-pad muting = instant beat variations without touching the notes."""
    r = get_ableton_connection().send_command(
        "set_drum_pad",
        params(
            track_index=track_index,
            device_index=device_index,
            note=note,
            mute=mute,
            solo=solo,
            name=name,
        ),
    )

    return f"Pad {note}: {json.dumps(r)}"


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False))
def rack_variation(
    ctx: Context, track_index: int, device_index: int, action: str, index: int | None = None
) -> str:
    """Rack macro snapshots. action: "store" (save current macros as a
    variation), "recall" (restore variation `index`), "randomize" (randomize
    all macro knobs - instant sound-design exploration)."""
    r = get_ableton_connection().send_command(
        "rack_variation",
        params(track_index=track_index, device_index=device_index, action=action, index=index),
    )
    return f"{action}: variations={r.get('variation_count')}"


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False))
def set_simpler_playback_mode(ctx: Context, track_index: int, device_index: int, mode: int) -> str:
    """Set a Simpler device's playback mode: 0 = Classic, 1 = One-Shot, 2 = Slicing.
    Slicing chops the sample into playable slices, central to lofi/hip-hop
    sampling. Errors if the device at that index is not a Simpler."""
    r = get_ableton_connection().send_command(
        "set_simpler_playback_mode",
        {"track_index": track_index, "device_index": device_index, "mode": mode},
    )
    return f"Simpler '{r.get('device')}' playback mode: {r.get('playback_mode')}"


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True, idempotentHint=True))
def replace_simpler_sample(
    ctx: Context, track_index: TrackIndex, device_index: DeviceIndex, path: str
) -> str:
    """Replace a Simpler sample with an absolute local audio-file path. Requires Live 12.4+
    AND runtime API support; otherwise fails before writing. Replaces musical content:
    confirm the target and preserve the original set. Readback is not an audio audition.
    """
    return json.dumps(
        get_ableton_connection().send_command(
            "replace_simpler_sample",
            {"track_index": track_index, "device_index": device_index, "path": path},
        ),
        indent=2,
    )


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def get_device_routing(ctx: Context, track_index: int, device_index: int) -> str:
    """Read a device's audio-input (sidechain) routing: current input type/channel
    and the available options. Only sidechain-capable devices (Compressor, Gate)
    have this. Use the options with set_device_routing to pick a sidechain source."""
    r = get_ableton_connection().send_command(
        "get_device_routing", {"track_index": track_index, "device_index": device_index}
    )
    return json.dumps(r, indent=2)


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False))
def set_device_routing(
    ctx: Context, track_index: int, device_index: int, field: str, display_name: str
) -> str:
    """Set a device's sidechain audio input. `field` is "input_routing_type" (the
    source track/return) or "input_routing_channel" (Pre FX / Post FX / Post Mixer);
    `display_name` is one of the options from get_device_routing. For ducking, also
    enable the device's Sidechain parameter via set_device_parameter."""
    r = get_ableton_connection().send_command(
        "set_device_routing",
        {
            "track_index": track_index,
            "device_index": device_index,
            "field": field,
            "display_name": display_name,
        },
    )
    return f"'{r.get('device')}' {field}: {r.get(field)}"


def _chain_wire(track_index, track_type, rack_device_index, chain_index, **more):
    wire = {"track_index": track_index, "track_type": track_type}
    if rack_device_index is not None or chain_index is not None:
        wire["rack_device_index"] = rack_device_index
        wire["chain_index"] = chain_index
    wire.update(more)
    return wire


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False))
def insert_device(
    ctx: Context,
    track_index: int,
    device_name: str,
    index: int | None = None,
    track_type: RackTrackType = "track",
    rack_device_index: RackDeviceIndex = None,
    chain_index: ChainIndex = None,
) -> str:
    """Insert a Live device by its browser name ('Utility', 'Erosion', 'EQ Eight') at a
    0-based position in a track's chain - the one place load_instrument_or_effect
    cannot reach (before the first audio effect). index omitted = end of chain.
    Live 12.3+ (Track.insert_device). track_type reaches return tracks and the
    Master track; rack_device_index + chain_index target a chain inside a rack.
    Instruments still go to the instrument slot, MIDI effects before it."""
    wire = _chain_wire(
        track_index, track_type, rack_device_index, chain_index, device_name=device_name
    )
    if index is not None:
        wire["index"] = index
    r = get_ableton_connection().send_command("insert_device", wire)
    return (
        f"Inserted '{r.get('device')}' on '{r.get('track')}' at device index "
        f"{r.get('device_index')} ({r.get('device_count')} devices)"
    )


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False))
def move_device(
    ctx: Context,
    track_index: int,
    device_index: int,
    new_index: int,
    track_type: RackTrackType = "track",
    rack_device_index: RackDeviceIndex = None,
    chain_index: ChainIndex = None,
) -> str:
    """Reorder a device within its chain: the device at device_index ends up at
    new_index (both 0-based, final positions). Live 12.3+ (Song.move_device).
    Live keeps instrument / MIDI-effect / audio-effect sections in order, so a
    move across sections is refused or clamped by Live. Returns the new order."""
    wire = _chain_wire(
        track_index,
        track_type,
        rack_device_index,
        chain_index,
        device_index=device_index,
        new_index=new_index,
    )
    r = get_ableton_connection().send_command("move_device", wire)
    return (
        f"'{r.get('device')}' now at device index {r.get('device_index')} on "
        f"'{r.get('track')}': {' > '.join(r.get('order', []))}"
    )


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
def replace_device(
    ctx: Context,
    track_index: int,
    device_index: int,
    device_name: str,
    track_type: RackTrackType = "track",
    copy_parameters: bool = True,
    rack_device_index: RackDeviceIndex = None,
    chain_index: ChainIndex = None,
) -> str:
    """Swap the device at device_index for a Live device named as in the browser,
    keeping the position: the new device is inserted right after, same-named
    parameters are copied (clamped to the new ranges), then the old device is
    deleted. Parameters that exist only on the old device are listed as not
    copied - set them by hand (e.g. Erosion Legacy 'Mode' vs Erosion 'Noise
    Blend'). Live 12.3+. One undo step per underlying edit."""
    wire = _chain_wire(
        track_index,
        track_type,
        rack_device_index,
        chain_index,
        device_index=device_index,
        device_name=device_name,
        copy_parameters=copy_parameters,
    )
    r = get_ableton_connection().send_command("replace_device", wire)
    msg = (
        f"Replaced '{r.get('replaced')}' with '{r.get('with')}' at device index "
        f"{r.get('device_index')} on '{r.get('track')}'"
    )
    if r.get("copied"):
        msg += f"; copied: {', '.join(r['copied'])}"
    if r.get("not_copied"):
        msg += f"; NOT copied (no same-named parameter): {', '.join(r['not_copied'])}"
    return msg
