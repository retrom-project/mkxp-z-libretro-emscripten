#!/usr/bin/env python3
"""Apply the reviewed WASI Ruby source patches when mkxp-z clones Ruby."""

from __future__ import annotations

import argparse
from pathlib import Path


PATCHES = ("ruby-try-catch-unwind.patch",)
ANCHOR = "\tcd $(RUBY_SRC) && $(GIT) apply $(PWD)/ruby-prng-time.patch\n"


def patch_makefile(source: str, recipe: Path) -> str:
    lines = "".join(f"\tcd $(RUBY_SRC) && $(GIT) apply {recipe / name}\n" for name in PATCHES)
    if source.count(ANCHOR) != 1 or lines in source:
        raise ValueError("MKXP_RUBY_PATCH_SOURCE_INVALID")
    return source.replace(ANCHOR, ANCHOR + lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    root = parser.parse_args().source.resolve()
    makefile = root / "mkxp-z/libretro/Makefile"
    makefile.write_text(patch_makefile(makefile.read_text(encoding="utf-8"), root / ".github/rpg-runtime"),
                        encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
