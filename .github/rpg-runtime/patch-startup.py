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


def patch_keyboard(source: str) -> str:
    """Read the raw libretro keyboard with desktop mkxp-z's default RGSS bindings."""
    return replace_exact(source,
        "        for (uint8_t i = 0; i < NUM_BUTTONCODES; ++i)\n"
        "            buttonStates[i] = getMappedState<false, false>(i);\n"
        "    }\n",
        "        for (uint8_t i = 0; i < NUM_BUTTONCODES; ++i)\n"
        "            buttonStates[i] = getMappedState<false, false>(i);\n"
        "\n"
        "        /* Same defaults as desktop mkxp-z (keybindings.cpp); the browser has no\n"
        "         * keyboard-to-RetroPad binds, so each key reaches the game once. */\n"
        "        static const struct { uint16_t key; uint8_t button; } keyboardBindings[] = {\n"
        "            {RETROK_LEFT, Input::Left}, {RETROK_RIGHT, Input::Right},\n"
        "            {RETROK_UP, Input::Up}, {RETROK_DOWN, Input::Down},\n"
        "            {RETROK_SPACE, Input::C}, {RETROK_RETURN, Input::C},\n"
        "            {RETROK_ESCAPE, Input::B}, {RETROK_KP0, Input::B}, {RETROK_LSHIFT, Input::A},\n"
        "            {RETROK_x, Input::B}, {RETROK_d, Input::Z}, {RETROK_q, Input::L},\n"
        "            {RETROK_w, Input::R}, {RETROK_a, Input::X}, {RETROK_s, Input::Y},\n"
        "        };\n"
        "        for (const auto &binding : keyboardBindings)\n"
        "            buttonStates[binding.button] = buttonStates[binding.button] || keyboardStates[binding.key];\n"
        "        if (rgssVer == 1) {\n"
        "            buttonStates[Input::A] = buttonStates[Input::A] || keyboardStates[RETROK_z];\n"
        "            buttonStates[Input::C] = buttonStates[Input::C] || keyboardStates[RETROK_c];\n"
        "        } else {\n"
        "            buttonStates[Input::C] = buttonStates[Input::C] || keyboardStates[RETROK_z];\n"
        "        }\n"
        "    }\n")


def patch_forced_assert(source: str) -> str:
    """Sandbox traps and forced assertions abort the core thread; publish the failure first."""
    source = replace_exact(source, "extern retro_log_printf_t mkxp_retro_log_printf;\n",
        "extern retro_log_printf_t mkxp_retro_log_printf;\n"
        "#  ifdef __EMSCRIPTEN__\n"
        "extern \"C\" void runtime_game_failed(void);\n"
        "#    define MKXPZ_RUNTIME_GAME_FAILED() runtime_game_failed()\n"
        "#  else\n"
        "#    define MKXPZ_RUNTIME_GAME_FAILED() ((void)0)\n"
        "#  endif\n")
    return replace_exact(source,
        "        ::mkxp_retro_log_printf(RETRO_LOG_ERROR, fmt, message); \\\n"
        "        std::fflush(stderr); \\\n",
        "        ::mkxp_retro_log_printf(RETRO_LOG_ERROR, fmt, message); \\\n"
        "        std::fflush(stderr); \\\n"
        "        MKXPZ_RUNTIME_GAME_FAILED(); \\\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    root = parser.parse_args().source / "mkxp-z"
    for relative, patcher in (("src/display/font.cpp", patch_font),
                              ("src/core.cpp", patch_core),
                              ("src/util/forced-assert.h", patch_forced_assert),
                              ("src/input/input-retro.cpp", patch_keyboard)):
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
