#!/usr/bin/env python3
"""Let the embedding page choose which realm's Gamepad API the linked core samples."""

from __future__ import annotations

import argparse
from pathlib import Path


OLD = ("try{if(navigator.getGamepads)return(JSEvents.lastGamepadState=navigator.getGamepads())?0:-1}"
       "catch(e){navigator.getGamepads=null}")
# The core module runs in the embedding page's realm while the game frame owns
# input; Module.retromGamepadNavigator selects that frame's (filtered) pads.
NEW = ('var gamepadNavigator=Module["retromGamepadNavigator"]||navigator;'
       "try{if(gamepadNavigator.getGamepads)return(JSEvents.lastGamepadState=gamepadNavigator.getGamepads())?0:-1}"
       "catch(e){gamepadNavigator.getGamepads=null}")


def patch_linked_js(source: str) -> str:
    if source.count(OLD) != 1 or NEW in source:
        raise ValueError("MKXP_GAMEPAD_SOURCE_INVALID")
    return source.replace(OLD, NEW)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--js", type=Path, required=True)
    path = parser.parse_args().js
    path.write_text(patch_linked_js(path.read_text(encoding="utf-8")), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
