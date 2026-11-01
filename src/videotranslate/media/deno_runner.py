#!/usr/bin/env python3
"""Offline bounded Deno gateway used by the official yt-dlp EJS provider.

Only stdin JavaScript and --version are supported. Caller flags never grant
permissions; ambient credentials, files, subprocesses and network are denied.
This is a subprocess entrypoint and deliberately imports only the standard library.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time

MAX_SCRIPT = 16 * 1024 * 1024
MAX_OUTPUT = 1024 * 1024
ERROR = "JavaScript runtime unavailable"
# The initial module graph contains only this fixed bootstrap. Supplied code is
# runtime data: Deno must not pre-resolve its literal file imports with the
# implicit entry-module read privilege (which --deny-read does not constrain).
BOOTSTRAP = """const code = await new Response(Deno.stdin.readable).text();
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
await new AsyncFunction(code)();
"""


def run_script(code, *, timeout=30):
    encoded = code.encode("utf-8") if isinstance(code, str) else code
    if not isinstance(encoded, bytes) or len(encoded) > MAX_SCRIPT:
        raise ValueError(ERROR)
    binary = shutil.which("deno")
    if not binary:
        raise ValueError(ERROR)
    args = [
        binary,
        "run",
        "--ext=js",
        "--no-code-cache",
        "--no-prompt",
        "--no-remote",
        "--no-npm",
        "--cached-only",
        "--no-lock",
        "--node-modules-dir=none",
        "--no-config",
        "--deny-net",
        "--deny-env",
        "--deny-read",
        "--deny-write",
        "--deny-run",
        "--deny-ffi",
        "--deny-sys",
        "--v8-flags=--max-old-space-size=128",
    ]
    with tempfile.TemporaryDirectory(prefix="videotranslate-js-") as directory:
        bootstrap = os.path.join(directory, "bootstrap.js")
        with open(bootstrap, "w", encoding="utf-8") as entry:
            entry.write(BOOTSTRAP)
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": directory,
            "DENO_DIR": directory,
            "DENO_NO_UPDATE_CHECK": "1",
            "NO_COLOR": "1",
        }
        with (
            tempfile.TemporaryFile() as source,
            tempfile.TemporaryFile() as out,
            tempfile.TemporaryFile() as err,
        ):
            source.write(encoded)
            source.seek(0)
            process = subprocess.Popen(
                [*args, bootstrap], stdin=source, stdout=out, stderr=err, env=env, cwd=directory
            )
            try:
                deadline = time.monotonic() + min(timeout, 30)
                while process.poll() is None:
                    if (
                        time.monotonic() >= deadline
                        or out.tell() > MAX_OUTPUT
                        or err.tell() > MAX_OUTPUT
                    ):
                        raise ValueError(ERROR)
                    time.sleep(0.02)
                if process.returncode or out.tell() > MAX_OUTPUT or err.tell() > MAX_OUTPUT:
                    raise ValueError(ERROR)
                out.seek(0)
                return out.read(MAX_OUTPUT)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()


def main():
    try:
        if sys.argv[1:] == ["--version"]:
            binary = shutil.which("deno")
            if not binary:
                raise ValueError(ERROR)
            result = subprocess.run(
                [binary, "--version"],
                capture_output=True,
                timeout=5,
                env={"DENO_NO_UPDATE_CHECK": "1", "NO_COLOR": "1"},
            )
            if result.returncode or len(result.stdout) > 1024:
                raise ValueError(ERROR)
            sys.stdout.buffer.write(result.stdout)
        else:
            code = sys.stdin.buffer.read(MAX_SCRIPT + 1)
            sys.stdout.buffer.write(run_script(code))
    except Exception:
        sys.stderr.write(ERROR + "\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
