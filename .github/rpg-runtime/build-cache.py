#!/usr/bin/env python3
"""Verified, worktree-local caches for the explicit MKXP build."""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import urllib.request


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def inventory(root: Path) -> dict[str, str]:
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("MKXP_BUILD_CACHE_SYMLINK")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = digest(path)
    return result


def store_artifacts(source: Path, target: Path) -> None:
    if target.exists():
        raise ValueError("MKXP_BUILD_CACHE_ALREADY_EXISTS")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".stage1-", dir=target.parent) as temporary:
        work = Path(temporary)
        shutil.copytree(source, work / "files")
        files = inventory(work / "files")
        if not files:
            raise ValueError("MKXP_BUILD_CACHE_EMPTY")
        (work / "manifest.json").write_text(json.dumps(files, sort_keys=True), encoding="utf-8")
        # Rename a child, not TemporaryDirectory itself, so its cleanup remains scoped.
        published = work / "publish"
        published.mkdir()
        (work / "files").rename(published / "files")
        (work / "manifest.json").rename(published / "manifest.json")
        published.rename(target)


def restore_artifacts(source: Path, target: Path) -> bool:
    if not source.exists():
        return False
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if not manifest or inventory(source / "files") != manifest:
        raise ValueError("MKXP_BUILD_CACHE_INVALID")
    shutil.copytree(source / "files", target)
    return True


def phase_recipe(source: Path, phase: str) -> str:
    script = (source / ".github/rpg-runtime/build-web.sh").read_text(encoding="utf-8")
    following, image = {
        "stage1": ("core", "stage1_image="),
        "core": ("frontend", "emscripten_image="),
    }[phase]
    start, end = "build_" + phase + "() {\n", "\nbuild_" + following + "() {\n"
    images = [line for line in script.splitlines() if line.startswith(image)]
    if script.count(start) != 1 or script.count(end) != 1 or len(images) != 1:
        raise ValueError("MKXP_BUILD_RECIPE_INVALID")
    return images[0] + "\n" + script.split(start, 1)[1].split(end, 1)[0]


def stage1_key(source: Path) -> str:
    inputs = inventory(source / "mkxp-z")
    # Git's portable object metadata is not compiler input.
    inputs = {name: value for name, value in inputs.items() if ".git" not in Path(name).parts}
    inputs["recipe/stage1"] = hashlib.sha256(phase_recipe(source, "stage1").encode()).hexdigest()
    for name in ("patch-runtime.py", "mkxp-deterministic-bindings.patch", "patch-ruby.py",
                 "ruby-try-catch-unwind.patch"):
        inputs["recipe/" + name] = digest(source / ".github/rpg-runtime" / name)
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()


def core_key(source: Path) -> str:
    inputs = {
        "stage1": stage1_key(source),
        "recipe": phase_recipe(source, "core"),
        "memory_patch": digest(source / ".github/rpg-runtime/patch-build-memory.py"),
        "startup_patch": digest(source / ".github/rpg-runtime/patch-startup.py"),
        "zip_stat_patch": digest(source / ".github/rpg-runtime/physfs-metadata-stat.patch"),
    }
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()


def cache_wrap(wrap: Path, cache: Path) -> None:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(wrap)
    declaration = parser["wrap-file"]
    name, expected = declaration["source_filename"], declaration["source_hash"]
    if Path(name).name != name or len(expected) != 64:
        raise ValueError("MKXP_DEPENDENCY_DECLARATION_INVALID")
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / name
    if target.exists():
        if digest(target) != expected:
            raise ValueError("MKXP_DEPENDENCY_HASH_INVALID")
        return
    url = declaration["source_url"]
    if url.startswith("https://ftpmirror.gnu.org/"):
        url = url.replace("https://ftpmirror.gnu.org/", "https://ftp.gnu.org/gnu/", 1)
    with tempfile.NamedTemporaryFile(prefix=".download-", dir=cache, delete=False) as temporary:
        downloaded = Path(temporary.name)
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                shutil.copyfileobj(response, temporary)
            temporary.flush()
            os.fsync(temporary.fileno())
            if digest(downloaded) != expected:
                raise ValueError("MKXP_DEPENDENCY_HASH_INVALID")
            downloaded.rename(target)
        finally:
            downloaded.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("key", "core-key", "restore", "store", "wrap"))
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path, nargs="?")
    args = parser.parse_args()
    if args.mode == "key":
        print(stage1_key(args.source))
    elif args.mode == "core-key":
        print(core_key(args.source))
    elif args.mode == "restore":
        print("hit" if restore_artifacts(args.source, args.target) else "miss")
    elif args.mode == "store":
        store_artifacts(args.source, args.target)
    else:
        cache_wrap(args.source, args.target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
