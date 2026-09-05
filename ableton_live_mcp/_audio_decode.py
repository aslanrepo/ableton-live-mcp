"""Local audio decoder worker, kept separate from MCP startup and time-limited by its caller."""

import array
import json
import math
import re
import sys
from pathlib import Path

FORMATS = {
    ".wav": "wav",
    ".wave": "wav",
    ".aif": "aiff",
    ".aiff": "aiff",
    ".aifc": "aiff",
    ".flac": "flac",
    ".ogg": "ogg",
    ".oga": "ogg",
    ".mp3": "mp3",
    ".aac": "aac",
    ".m4a": "mov",
    ".mp4": "mov",
}
MAX_SAMPLES = 32_000_000


def _db(value):
    return round(20 * math.log10(value), 4) if value else None


def decode_and_measure(path, max_seconds):
    import av

    source = Path(path)
    if not math.isfinite(max_seconds) or not 0 < max_seconds <= 120:
        raise ValueError("max_seconds must be finite and in (0, 120]")
    if not source.is_file() or source.suffix.lower() not in FORMATS:
        raise ValueError("Provide an existing supported local audio file")
    if source.stat().st_size > 512 * 1024 * 1024:
        raise ValueError("File exceeds the 512 MiB safety limit")
    # Explicit demuxers exclude playlists; file objects plus disabled protocols prevent
    # the decoder from opening remote URLs or external media references in the file.
    with (
        source.open("rb") as handle,
        av.open(
            handle,
            format=FORMATS[source.suffix.lower()],
            options={"protocol_whitelist": "", "enable_drefs": "0", "err_detect": "explode"},
        ) as container,
    ):
        if not container.streams.audio:
            raise ValueError("File contains no audio stream")
        stream = container.streams.audio[0]
        stream.codec_context.thread_count = 1
        rate = stream.codec_context.sample_rate
        layout = stream.codec_context.layout
        channels = len(layout.channels)
        if not 1 <= channels <= 8 or not 1 <= rate <= 384000:
            raise ValueError("Supported: 1–8 channels and sample rates up to 384 kHz")
        requested = int(rate * max_seconds)
        limit = min(requested, MAX_SAMPLES // channels)
        if limit < 1:
            raise ValueError("No audio frames to measure")
        codec = stream.codec_context.name
        pcm_bits = re.match(r"pcm_[suf](\d+)", codec)
        bit_depth = int(pcm_bits[1]) if pcm_bits else None
        estimate = (
            float(stream.duration * stream.time_base) if stream.duration is not None else None
        )
        if estimate is not None and (not math.isfinite(estimate) or estimate < 0):
            estimate = None
        converter = av.AudioResampler(format="dblp", layout=layout, rate=rate)
        peak, square, sums, full_scale = ([0.0] * channels for _ in range(4))
        count, partial = 0, False
        for frame in container.decode(stream):
            if frame.sample_rate != rate or frame.layout != layout:
                raise ValueError("Audio format changes within the file")
            if frame.is_corrupt:
                raise ValueError("Corrupt audio frame")
            if count >= limit and frame.samples:
                partial = True
                break
            for decoded in converter.resample(frame):
                take = min(decoded.samples, limit - count)
                for channel, plane in enumerate(decoded.planes):
                    values = array.array("d")
                    values.frombytes(bytes(plane)[: take * 8])
                    if any(not math.isfinite(v) for v in values):
                        raise ValueError("Audio contains NaN or infinite samples")
                    peak[channel] = max(peak[channel], max(map(abs, values), default=0))
                    sums[channel] += math.fsum(values)
                    square[channel] += math.fsum(v * v for v in values)
                    full_scale[channel] += sum(abs(v) >= 1.0 for v in values)
                count += take
                if take < decoded.samples:
                    partial = True
                    break
            if partial:
                break
        if not count:
            raise ValueError("No audio frames to measure")
        metrics = []
        for channel in range(channels):
            rms = math.sqrt(square[channel] / count)
            metrics.append(
                {
                    "channel": channel,
                    "sample_peak_dbfs": _db(peak[channel]),
                    "rms_dbfs": _db(rms),
                    "dc_offset": sums[channel] / count,
                    "full_scale_samples": int(full_scale[channel]),
                    "crest_factor_db": _db(peak[channel] / rms) if rms else None,
                }
            )
        return {
            "evidence": "measured_decoded_audio",
            "codec": codec,
            "container": container.format.name,
            "audio_stream_index": stream.index,
            "sample_rate": rate,
            "bit_depth": bit_depth,
            "duration_seconds": None if partial else count / rate,
            "duration_estimate_seconds": estimate,
            "analyzed_seconds": count / rate,
            "partial": partial,
            "limit_reason": ("sample_budget" if limit < requested else "max_seconds")
            if partial
            else None,
            "channels": metrics,
            "limitations": "Decoded samples at original rate and channel layout; no normalization. "
            "First audio stream only. Lossy decoding cannot recover the original signal. "
            "Sample peak is not true peak; RMS is not LUFS. Full-scale samples count decoded "
            "magnitudes >= 1.0, not proof of clipping; floating point can exceed 0 dBFS. "
            "Null dB means silence; bit_depth is null for non-PCM codecs. "
            "Full duration is unknown for partial analysis; container duration is an estimate.",
        }


if __name__ == "__main__":
    try:
        print(json.dumps(decode_and_measure(sys.argv[1], float(sys.argv[2])), allow_nan=False))
    except Exception as exc:
        print(json.dumps({"error": f"Unable to decode audio: {exc}"}))
        sys.exit(1)
