#!/usr/bin/env python3
"""Preserve native argument ownership across a rescued Ruby longjmp.

Patch the generated C++ bindings during the core phase. The WASI Ruby binary
and its content-verified Stage 1 cache remain unchanged.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re


def replace_exact(source: str, old: str, new: str) -> str:
    if source.count(old) != 1 or new in source:
        raise ValueError("MKXP_BINDING_CLEANUP_SOURCE_INVALID")
    return source.replace(old, new)


def patch_bindings(header: str, source: str) -> tuple[str, str]:
    declaration = re.compile(
        r"(    struct (\w+) : boost::asio::coroutine \{\n"
        r"        typedef decl_slots<([^>]*)> slots;.*?"
        r"        struct binding_base &bind;\n)(    };)", re.S)
    patched = 0
    for match in list(declaration.finditer(header)):
        name, slots = match[2], match[3]
        if not slots:
            continue
        types = slots.split(", ")
        if any(value != "wasm_ptr_t" for value in types):
            raise ValueError("MKXP_BINDING_CLEANUP_SOURCE_INVALID")
        count = len(types)
        header = replace_exact(header, match[0],
            match[1] + f"        wasm_ptr_t cleanup_slots[{count}] = {{}};\n" + match[4])
        start = source.index(f"{name}::{name}(struct binding_base &b)")
        cleanup = source.index(f"void {name}::end() noexcept {{", start)
        end = source.index("\n}", cleanup) + 2
        original = source[start:end]
        call, destructor = source[start:cleanup], source[cleanup:end]
        # Record ownership immediately, including partially initialized calls.
        call = re.sub(r"_SBINDGEN_SLOT\((\d+)\) = ",
            lambda value: f"cleanup_slots[{value[1]}] = " + value[0], call)
        # A fresh checkpoint instance recreates its C++ coroutine, then resumes
        # through this loop with its serialized sandbox slots still intact.
        snapshot = "".join(f"            cleanup_slots[{i}] = _SBINDGEN_SLOT({i});\n" for i in range(count))
        call = replace_exact(call, "        for (;;) {\n", "        for (;;) {\n" + snapshot)
        # Orphaned calls never resume: Ruby may already have reused their slots.
        destructor = re.sub(r"_SBINDGEN_SLOT\((\d+)\)", r"cleanup_slots[\1]", destructor)
        source = replace_exact(source, original, call + destructor)
        patched += 1
    if patched == 0:
        raise ValueError("MKXP_BINDING_CLEANUP_SOURCE_INVALID")
    return header, source


def patch_frames(source: str) -> str:
    source = replace_exact(source, "                // Otherwise, create a new stack frame\n", """                // Ruby may already have unwound past the orphaned frames below.
                // Their cleanup must not move its current machine stack pointer.
                const wasm_ptr_t current_stack_pointer = w2c_ruby_rb_wasm_get_stack_pointer(&b.instance());

                // Otherwise, create a new stack frame
""")
    return replace_exact(source,
        "                if (++fiber->stack_index == 0) {\n",
        "                w2c_ruby_rb_wasm_set_stack_pointer(&b.instance(), current_stack_pointer);\n\n"
        "                if (++fiber->stack_index == 0) {\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    root = parser.parse_args().source / "mkxp-z"
    header = root / "libretro/build/libretro-stage1/sandbox-bindgen/mkxp-sandbox-bindgen.h"
    implementation = header.with_suffix(".cpp")
    patched_header, patched_source = patch_bindings(header.read_text(), implementation.read_text())
    header.write_text(patched_header, encoding="utf-8")
    implementation.write_text(patched_source, encoding="utf-8")
    frames = root / "binding-sandbox/binding-base.h"
    frames.write_text(patch_frames(frames.read_text()), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
