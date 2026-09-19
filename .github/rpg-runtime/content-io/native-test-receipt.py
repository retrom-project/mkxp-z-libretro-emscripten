"""Bind the native Content I/O fixture to its exact source and compiler inputs."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

source, output = (Path(value) for value in sys.argv[1:])
recipe = ".github/rpg-runtime/content-io/"
inputs = [recipe + name for name in (
    "test-native.cpp", "retrom-content-bridge.cpp", "retrom-content-manifest.cpp",
    "retrom-content-bridge.h", "build-native-test.sh", "native-test-receipt.py",
)] + [".github/rpg-runtime/patch-remote-content.py", "retroarch/Makefile.emscripten",
      "retroarch/frontend/drivers/platform_emscripten.c"]


def fingerprint(root, names):
    result = {}
    for name in names:
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise ValueError("NATIVE_FIXTURE_INPUT_INVALID")
        data = path.read_bytes()
        result[name] = {"sizeBytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return result


value = {
    "schemaVersion": 1, "kind": "MKXP_CONTENT_IO_NATIVE_FIXTURE",
    "compiler": subprocess.check_output(["em++", "--version"], text=True).splitlines()[0],
    "inputs": fingerprint(source, inputs),
    "outputs": fingerprint(output, ["content-native.js", "content-native.wasm"]),
}
(output / "native-fixture.json").write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
