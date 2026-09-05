#!/usr/bin/env python3
"""Validate the host-independent mkxp-z release pair and emit metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import runpy
import subprocess
from pathlib import Path


TAG = re.compile(r"^retrom-core-f2efc98-r[1-9][0-9]*$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_GITLINKS = {
    "mkxp-z": "f2efc98a344c505a66820e06d6508092719b8dd2",
    "retroarch": "69a4f0ea1e8aaf442ae4858f2e7f2b31a1776576",
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def gitlink(source: Path, path: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", f"HEAD:{path}"],
        text=True,
    ).strip()


def validate_browser_abi(js_bytes: bytes) -> None:
    for export in (b"_runtime_get_frame_count", b"_runtime_get_state_result",
                   b"_runtime_request_state", b"_runtime_request_exit"):
        if export not in js_bytes:
            raise ValueError("RPG_RUNTIME_RELEASE_STATE_ABI_INVALID")


def validate_remote_content(platform_source: str, js_bytes: bytes, patch_file: Path) -> None:
    # Both callers supply the pristine checkout/snapshot. Reapply the exact
    # recipe in memory to check its anchors without mutating release sources.
    patched_source = runpy.run_path(str(patch_file))["patch_retroarch"](platform_source)
    if (
        "FETCH_CHUNK_SIZE_BYTES" not in patched_source
        or b"FETCHFS_RANGE_REQUIRED" not in js_bytes
        or b"FETCHFS_RANGE_PROTOCOL_INVALID" not in js_bytes
        or b"FETCHFS_RANGE_LENGTH_INVALID" not in js_bytes
    ):
        raise ValueError("RPG_RUNTIME_RELEASE_REMOTE_CONTENT_INVALID")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()

    if TAG.fullmatch(args.tag) is None or COMMIT.fullmatch(args.commit) is None:
        raise SystemExit("RPG_RUNTIME_RELEASE_IDENTITY_INVALID")
    if any(gitlink(args.source, path) != expected for path, expected in EXPECTED_GITLINKS.items()):
        raise SystemExit("RPG_RUNTIME_RELEASE_SOURCE_INVALID")

    patch = args.source / ".github/rpg-runtime/mkxp-deterministic-bindings.patch"
    patch_text = patch.read_text(encoding="utf-8")
    runtime_patch = args.source / ".github/rpg-runtime/patch-runtime.py"
    runtime_patch_text = runtime_patch.read_text(encoding="utf-8")
    remote_content_patch = args.source / ".github/rpg-runtime/patch-remote-content.py"
    remote_content_patch_text = remote_content_patch.read_text(encoding="utf-8")
    if (
        "/dev/urandom" not in patch_text
        or "printf '%s'" not in patch_text
        or "sha256sum" not in patch_text
        or "mkxp_retro::sandbox.has_value()" not in runtime_patch_text
        or "RPG_RUNTIME_RESTORE_GUARD_SOURCE_INVALID" not in runtime_patch_text
        or "FETCH_CHUNK_SIZE_BYTES" not in remote_content_patch_text
        or "FETCHFS_RANGE_PROTOCOL_INVALID" not in remote_content_patch_text
        or "FETCHFS_RANGE_LENGTH_INVALID" not in remote_content_patch_text
    ):
        raise SystemExit("RPG_RUNTIME_RELEASE_BINDING_PATCH_INVALID")

    js_path = args.output / "mkxp-z_libretro.js"
    wasm_path = args.output / "mkxp-z_libretro.wasm"
    if js_path.is_symlink() or not js_path.is_file() or js_path.stat().st_size < 200_000:
        raise SystemExit("RPG_RUNTIME_RELEASE_JS_INVALID")
    if wasm_path.is_symlink() or not wasm_path.is_file() or wasm_path.stat().st_size < 40_000_000:
        raise SystemExit("RPG_RUNTIME_RELEASE_WASM_INVALID")
    if wasm_path.read_bytes()[:8] != b"\x00asm\x01\x00\x00\x00":
        raise SystemExit("RPG_RUNTIME_RELEASE_WASM_INVALID")
    platform_source = (
        args.source / "retroarch/frontend/drivers/platform_emscripten.c"
    ).read_text(encoding="utf-8")
    js_bytes = js_path.read_bytes()
    validate_remote_content(platform_source, js_bytes, remote_content_patch)
    validate_browser_abi(js_bytes)

    assets = []
    for path in (js_path, wasm_path):
        assets.append(
            {
                "filename": path.name,
                "observedSha256": digest(path),
                "sizeBytes": path.stat().st_size,
            }
        )
    metadata = {
        "adapterAbi": "mkxp-state",
        "assets": assets,
        "commit": args.commit,
        "digestPolicy": "OBSERVED_CACHE_INTEGRITY_ONLY",
        "remoteContent": {
            "chunkSizeEnvironment": "FETCH_CHUNK_SIZE_BYTES",
            "kind": "WASMFS_FETCH_RANGE_V1",
            "rangeRequired": True,
        },
        "repository": args.repository,
        "schemaVersion": 1,
        "sourceCommits": EXPECTED_GITLINKS,
        "tag": args.tag,
    }
    (args.output / "rpg-runtime-release.json").write_text(
        json.dumps(metadata, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
