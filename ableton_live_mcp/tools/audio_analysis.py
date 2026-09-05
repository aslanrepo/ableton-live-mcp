"""Bounded local audio measurements; no perceptual/mastering claims."""

import json
import math
import subprocess
import sys
import wave
from pathlib import Path

from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations

from ..app import mcp

SUPPORTED_SUFFIXES = {
    ".wav",
    ".wave",
    ".aif",
    ".aiff",
    ".aifc",
    ".flac",
    ".ogg",
    ".oga",
    ".mp3",
    ".aac",
    ".m4a",
    ".mp4",
}


def measure_audio(path, max_seconds=30.0):
    """Decode a local file in a time-limited process; retain exact integer WAV handling."""
    if not math.isfinite(max_seconds) or not 0 < max_seconds <= 120:
        raise ValueError("max_seconds must be finite and in (0, 120]")
    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError("Provide a local WAV, AIFF/AIFF-C, FLAC, Ogg, MP3, AAC or M4A/MP4 file")
    if source.stat().st_size > 512 * 1024 * 1024:
        raise ValueError("File exceeds the 512 MiB safety limit")
    if source.suffix.lower() == ".wav":
        try:
            # Determine format only: malformed PCM must not silently fall back to another parser.
            with wave.open(str(source), "rb"):
                pass
        except wave.Error:
            pass
        else:
            return measure_wav(source, max_seconds)
    worker = Path(__file__).parents[1] / "_audio_decode.py"
    try:
        result = subprocess.run(
            [sys.executable, str(worker), str(source), str(max_seconds)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Audio analysis exceeded the 60-second processing limit") from exc
    try:
        report = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise ValueError("Audio decoder failed; the file could not be analyzed") from exc
    if result.returncode or "error" in report:
        raise ValueError(report.get("error", "Audio decoder failed"))
    return report


def _db(value):
    return round(20 * math.log10(value), 4) if value > 0 else None


def measure_wav(path, max_seconds=30.0):
    if not math.isfinite(max_seconds) or not 0 < max_seconds <= 120:
        raise ValueError("max_seconds must be finite and in (0, 120]")
    source = Path(path).expanduser()
    if not source.is_file() or source.suffix.lower() != ".wav":
        raise ValueError("Provide an existing PCM .wav file")
    if source.stat().st_size > 512 * 1024 * 1024:
        raise ValueError("File exceeds the 512 MiB safety limit")
    try:
        with wave.open(str(source), "rb") as audio:
            channels, width, rate = audio.getnchannels(), audio.getsampwidth(), audio.getframerate()
            if width not in (1, 2, 3, 4) or not 1 <= channels <= 8 or not 1 <= rate <= 384000:
                raise ValueError("Supported: 8/16/24/32-bit integer PCM, 1–8 channels, <=384 kHz")
            total = audio.getnframes()
            limit = min(total, int(rate * max_seconds), 32_000_000 // channels)
            if limit == 0:
                raise ValueError("No audio frames to measure")
            peak, square, sums, clipped = ([0.0] * channels for _ in range(4))
            frames = 0
            scale = 2 ** (width * 8 - 1)
            while frames < limit:
                chunk = audio.readframes(min(4096, limit - frames))
                if not chunk or len(chunk) % (width * channels):
                    raise ValueError("Truncated or malformed PCM audio data")
                for offset in range(0, len(chunk), width):
                    channel = (offset // width) % channels
                    integer = (
                        chunk[offset] - 128
                        if width == 1
                        else int.from_bytes(chunk[offset : offset + width], "little", signed=True)
                    )
                    value = integer / scale
                    peak[channel] = max(peak[channel], abs(value))
                    square[channel] += value * value
                    sums[channel] += value
                    clipped[channel] += integer <= -scale or integer >= scale - 1
                frames += len(chunk) // (width * channels)
    except (wave.Error, EOFError) as exc:
        raise ValueError(
            "Unsupported or invalid WAV. Export integer PCM (not float/compressed)."
        ) from exc
    metrics = []
    for channel in range(channels):
        rms = math.sqrt(square[channel] / frames)
        metrics.append(
            {
                "channel": channel,
                "sample_peak_dbfs": _db(peak[channel]),
                "rms_dbfs": _db(rms),
                "dc_offset": sums[channel] / frames,
                "full_scale_samples": int(clipped[channel]),
                "crest_factor_db": _db(peak[channel] / rms) if rms else None,
            }
        )
    return {
        "evidence": "measured_pcm",
        "sample_rate": rate,
        "bit_depth": width * 8,
        "duration_seconds": total / rate,
        "analyzed_seconds": frames / rate,
        "partial": frames < total,
        "channels": metrics,
        "limitations": "Start of file only when partial. Sample peak is not true peak; "
        "RMS is not LUFS. Full-scale samples suggest possible clipping, "
        "not proof. Null dB means silence. No tonal/key/quality judgment.",
    }


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def analyze_audio_file(ctx: Context, path: str, max_seconds: float = 30.0) -> str:
    """Measure local WAV (integer/float), AIFF/AIFF-C, FLAC, Ogg Vorbis, MP3,
    AAC or M4A/MP4 (AAC/ALAC) without Live: per-channel sample peak/RMS dBFS,
    DC offset, crest factor and full-scale samples. Analyzes the first max_seconds
    (default 30, maximum 120); marks partial results. Not LUFS or true peak. No upload.
    Compressed files are measured after decoding; this does not recover lost audio.
    Files are read locally without modification, normalization or upload.
    """
    return json.dumps(measure_audio(path, max_seconds), indent=2, allow_nan=False)
