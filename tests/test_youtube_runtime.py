"""Real offline Deno capability boundary, independent of upstream availability."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def runtime(monkeypatch):
    candidate = shutil.which("deno") or "/tmp/vt-deno-v2.5.6/deno"
    if not Path(candidate).is_file():
        pytest.skip("Pinned Deno runtime not installed")
    monkeypatch.setenv(
        "PATH", str(Path(candidate).parent) + os.pathsep + os.environ.get("PATH", "")
    )
    from videotranslate.media import deno_runner

    return deno_runner


def test_offline_solver_executes_and_blocks_network_files_env_processes(monkeypatch):
    runner = runtime(monkeypatch)
    result = runner.run_script("console.log(1 + 2)")
    assert result == b"3\n"
    for code in [
        "await fetch('https://127.0.0.1/')",
        "Deno.readTextFileSync('/etc/passwd')",
        "Deno.env.get('HOME')",
        "new Deno.Command('sh').spawn()",
    ]:
        with pytest.raises(ValueError, match="JavaScript runtime unavailable"):
            runner.run_script(code)


def test_runtime_script_and_output_and_time_caps(monkeypatch):
    runner = runtime(monkeypatch)
    with pytest.raises(ValueError):
        runner.run_script("x" * (16 * 1024 * 1024 + 1))
    with pytest.raises(ValueError):
        runner.run_script("console.log('x'.repeat(2*1024*1024))")
    with pytest.raises(ValueError):
        runner.run_script("while(true){}", timeout=0.2)


def test_runtime_wrapper_cannot_take_permission_flags(monkeypatch):
    runner = runtime(monkeypatch)
    wrapper = Path(runner.__file__)
    process = subprocess.run(
        [str(wrapper), "run", "--allow-net", "-"],
        input=b"console.log(3)",
        capture_output=True,
        timeout=10,
    )
    # Caller flags are ignored. The fixed sandbox denies network regardless.
    assert process.returncode == 0 and process.stdout == b"3\n"
    process = subprocess.run(
        [str(wrapper), "run", "--allow-net", "-"],
        input=b"await fetch('https://127.0.0.1/')",
        capture_output=True,
        timeout=10,
    )
    assert process.returncode != 0


def test_pinned_runtime_wrapper_is_packaged_and_executable():
    from videotranslate.media import deno_runner

    path = Path(deno_runner.__file__)
    assert path.is_file() and os.access(path, os.X_OK)


@pytest.mark.parametrize("kind", ["static", "literal_dynamic", "computed_dynamic"])
def test_module_loader_cannot_read_synthetic_json_sentinel(monkeypatch, tmp_path, kind):
    import json

    runner = runtime(monkeypatch)
    fixture = tmp_path / "synthetic-only.json"
    fixture.write_text(json.dumps({"marker": "SYNTHETIC_ONLY_REVIEW_TOKEN"}))
    target = json.dumps(fixture.as_uri())
    if kind == "static":
        code = f'import x from {target} with {{type:"json"}}; console.log(x.marker);'
    elif kind == "literal_dynamic":
        code = f'const x = await import({target}, {{with:{{type:"json"}}}}); console.log(x.default.marker);'
    else:
        code = f'const target = {target}; const x = await import(target, {{with:{{type:"json"}}}}); console.log(x.default.marker);'
    with pytest.raises(ValueError, match="JavaScript runtime unavailable"):
        runner.run_script(code)


def test_trusted_bootstrap_preserves_await_and_official_ejs_challenge_execution(monkeypatch):
    import json

    import yt_dlp_ejs.yt.solver as solver

    runner = runtime(monkeypatch)
    # Same pinned lib/core composition and preprocessed Function path used by EJS.
    request = {
        "type": "preprocessed",
        "preprocessed_player": '_result.sig = s => s.split("").reverse().join(""); _result.n = s => s + "!";',
        "requests": [{"type": "sig", "challenges": ["abc"]}, {"type": "n", "challenges": ["xyz"]}],
    }
    code = (
        solver.lib()
        + "\nObject.assign(globalThis, lib);\n"
        + solver.core()
        + "\nawait Promise.resolve(); console.log(JSON.stringify(jsc("
        + json.dumps(request)
        + ")));"
    )
    result = json.loads(runner.run_script(code))
    assert result["type"] == "result"
    assert [row["data"] for row in result["responses"]] == [{"abc": "cba"}, {"xyz": "xyz!"}]
