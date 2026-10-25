#!/usr/bin/env python3
"""Keep localized fonts, ZIP metadata scans and game failures correct on Web."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil


def replace_exact(source: str, old: str, new: str) -> str:
    if source.count(old) != 1 or new in source:
        raise ValueError("MKXP_STARTUP_SOURCE_INVALID")
    return source.replace(old, new)


def patch_font(source: str) -> str:
    return replace_exact(source,
        "\t\tconst char *path = !req.regular.empty()\n"
        "\t\t                 ? req.regular.c_str() : req.other.c_str();",
        "\t\tconst char *path = req->c_str(); // Include localized SFNT aliases.")


def patch_zip(source: str) -> str:
    return replace_exact(source,
        "    else if (!zip_resolve(info->io, info, entry))\n        return 0;",
        "    /* Central-directory metadata is sufficient for regular-file stat.\n"
        "     * Validate its local header when opening bytes, not while listing\n"
        "     * every member of a seekable remote archive. */\n"
        "    else if ((entry->tree.isdir || (entry->resolved != ZIP_UNRESOLVED_FILE)) &&\n"
        "             !zip_resolve(info->io, info, entry))\n        return 0;")


def patch_core(source: str) -> str:
    source = replace_exact(source, '#include "core.h"\n',
        '#include "core.h"\n\n#ifdef __EMSCRIPTEN__\n'
        'extern "C" void runtime_game_failed(void);\n#endif\n')
    return replace_exact(source,
        '                LOG_PRINT(RETRO_LOG_ERROR, "Game threw an exception; terminating\\n");',
        '                LOG_PRINT(RETRO_LOG_ERROR, "Game threw an exception; terminating\\n");\n'
        '#ifdef __EMSCRIPTEN__\n                runtime_game_failed();\n#endif')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    root = parser.parse_args().source / "mkxp-z"
    for relative, patcher in (("src/display/font.cpp", patch_font), ("src/core.cpp", patch_core)):
        path = root / relative
        path.write_text(patcher(path.read_text()), encoding="utf-8")
    wrap = root / "subprojects/physfs.wrap"
    wrap.write_text(replace_exact(wrap.read_text(),
        "physfs-dir.patch, physfs-mkxp-polyfill.patch",
        "physfs-dir.patch, physfs-mkxp-polyfill.patch, physfs-metadata-stat.patch"), encoding="utf-8")
    shutil.copyfile(Path(__file__).with_name("physfs-metadata-stat.patch"),
                    root / "subprojects/packagefiles/physfs-metadata-stat.patch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
