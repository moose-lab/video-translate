"""Private isolated Rubber Band 4 C-API runner; no network or model imports.

Signatures match rubberband-c.h API3, v4.0.0. No CLI, clipping, gain retry,
engine fallback, or source-dependent code/filter text enters this process.
"""

import ctypes as C
import ctypes.util
import json
import math
import sys
from array import array
from pathlib import Path

BLOCK = 4096
RATE = 48000


def library():
    name = ctypes.util.find_library("rubberband")
    if not name and Path("/opt/homebrew/lib/librubberband.dylib").is_file():
        name = "/opt/homebrew/lib/librubberband.dylib"
    if not name:
        raise RuntimeError("CONFIGURATION")
    lib = C.CDLL(name)
    state, uint, integer, double = C.c_void_p, C.c_uint, C.c_int, C.c_double
    fp = C.POINTER(C.c_float)
    fpp = C.POINTER(fp)
    # Every symbol used has both argtypes and restype, including void functions.
    signatures = {
        "new": ([uint, uint, integer, double, double], state),
        "delete": ([state], None),
        "get_engine_version": ([state], integer),
        "set_expected_input_duration": ([state, uint], None),
        "set_time_ratio": ([state, double], None),
        "set_pitch_scale": ([state, double], None),
        "set_max_process_size": ([state, uint], None),
        "set_key_frame_map": ([state, uint, C.POINTER(uint), C.POINTER(uint)], None),
        "study": ([state, fpp, uint, integer], None),
        "process": ([state, fpp, uint, integer], None),
        "available": ([state], integer),
        "retrieve": ([state, fpp, uint], uint),
    }
    for suffix, (args, result) in signatures.items():
        fn = getattr(lib, "rubberband_" + suffix)
        fn.argtypes, fn.restype = args, result
    return lib


def run(config, raw, output, receipt_path, phase):
    if config.stat().st_size > 262144:
        raise ValueError("INVALID_MEDIA")
    data = json.loads(config.read_text())
    count, expected = data["input_frames"], data["output_frames"]
    if any(type(v) is not int or not 1 <= v <= 2764800000 for v in (count, expected)):
        raise ValueError("INVALID_MEDIA")
    keys = data["keys"]
    if type(keys) is not list or len(keys) > 3000 or raw.stat().st_size != count * 8:
        raise ValueError("INVALID_MEDIA")
    previous = (0, 0)
    for pair in keys:
        if (
            type(pair) is not list
            or len(pair) != 2
            or any(type(v) is not int for v in pair)
            or not previous[0] < pair[0] < count
            or not previous[1] < pair[1] < expected
        ):
            raise ValueError("INVALID_MEDIA")
        previous = pair
    lib = library()
    # Offline + R3 + deterministic single thread + channels together, fixed pitch1.
    state = lib.rubberband_new(RATE, 2, 0x20000000 | 0x00010000 | 0x10000000, expected / count, 1.0)
    if not state:
        raise RuntimeError("CONFIGURATION")
    try:
        if lib.rubberband_get_engine_version(state) != 3:
            raise RuntimeError("CONFIGURATION")
        lib.rubberband_set_max_process_size(state, BLOCK)
        lib.rubberband_set_expected_input_duration(state, count)
        lib.rubberband_set_time_ratio(state, expected / count)
        lib.rubberband_set_pitch_scale(state, 1.0)
        if keys:
            left = (C.c_uint * len(keys))(*(p[0] for p in keys))
            right = (C.c_uint * len(keys))(*(p[1] for p in keys))
            lib.rubberband_set_key_frame_map(state, len(keys), left, right)
        planes = [(C.c_float * BLOCK)() for _ in range(2)]
        pointers = (C.POINTER(C.c_float) * 2)(*planes)
        written, peak = 0, 0.0
        with output.open("xb") as out:

            def retrieve():
                nonlocal written, peak
                while True:
                    available = lib.rubberband_available(state)
                    if available <= 0:
                        return available
                    n = lib.rubberband_retrieve(state, pointers, min(BLOCK, available))
                    if not 0 < n <= BLOCK or written + n > expected:
                        raise ValueError("INVALID_MEDIA")
                    values = array("f")
                    for i in range(n):
                        for c in range(2):
                            value = planes[c][i]
                            if not math.isfinite(value):
                                raise ValueError("INVALID_MEDIA")
                            peak = max(peak, abs(value))
                            values.append(value)
                    if sys.byteorder != "little":
                        values.byteswap()
                    out.write(values.tobytes())
                    written += n

            for mode in ("study", "process"):
                phase.write_text(mode)
                with raw.open("rb") as source:
                    position = 0
                    while chunk := source.read(BLOCK * 8):
                        values = array("f")
                        values.frombytes(chunk)
                        if sys.byteorder != "little":
                            values.byteswap()
                        n = len(values) // 2
                        if len(values) % 2 or any(not math.isfinite(v) for v in values):
                            raise ValueError("INVALID_MEDIA")
                        for i in range(n):
                            for c in range(2):
                                planes[c][i] = values[i * 2 + c]
                        position += n
                        getattr(lib, "rubberband_" + mode)(
                            state, pointers, n, int(position == count)
                        )
                        if mode == "process":
                            retrieve()
                    if position != count:
                        raise ValueError("INVALID_MEDIA")
            if retrieve() != -1 or written != expected:
                raise ValueError("INVALID_MEDIA")
        receipt_path.write_text(
            json.dumps(
                {
                    "engine": 3,
                    "pitch_scale": 1,
                    "input_frames": count,
                    "output_frames": written,
                    "peak": peak,
                },
                allow_nan=False,
            )
        )
    finally:
        lib.rubberband_delete(state)


def main():
    try:
        if len(sys.argv) != 6:
            raise ValueError("INVALID_MEDIA")
        run(*(Path(p) for p in sys.argv[1:]))
    except BaseException:
        # Parent receives only bounded code; native diagnostics never become metadata.
        sys.stderr.write("OFFLINE_WARP_FAILED\n")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
