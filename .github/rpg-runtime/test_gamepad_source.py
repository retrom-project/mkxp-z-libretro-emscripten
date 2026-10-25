"""Check the linked core's Gamepad API source selection."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


RECIPE = Path(__file__).resolve().parent
# Exact sampler emitted by the pinned Emscripten image for this core.
LINKED = ("function _emscripten_sample_gamepad_data(){if(ENVIRONMENT_IS_PTHREAD)return proxyToMainThread(27,0,1);"
          "try{if(navigator.getGamepads)return(JSEvents.lastGamepadState=navigator.getGamepads())?0:-1}"
          "catch(e){navigator.getGamepads=null}return-1}")


def module():
    spec = importlib.util.spec_from_file_location("gamepad_source", RECIPE / "patch-gamepad-source.py")
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


class GamepadSourceTests(unittest.TestCase):
    def test_sampler_reads_the_embedder_selected_navigator(self):
        patched = module().patch_linked_js(LINKED)
        node = shutil.which("node")
        if node is None:
            self.skipTest("node unavailable")
        script = (
            "var ENVIRONMENT_IS_PTHREAD=false,JSEvents={};"
            "var navigator={getGamepads:()=>['page']};"
            "var Module={retromGamepadNavigator:{getGamepads:()=>['frame']}};"
            + patched +
            "if(_emscripten_sample_gamepad_data()!==0||JSEvents.lastGamepadState[0]!=='frame')process.exit(2);"
            "delete Module.retromGamepadNavigator;"
            "if(_emscripten_sample_gamepad_data()!==0||JSEvents.lastGamepadState[0]!=='page')process.exit(3);"
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "probe.js"
            path.write_text(script)
            self.assertEqual(subprocess.run([node, str(path)], capture_output=True).returncode, 0)

    def test_patch_rejects_drift_and_reapplication(self):
        patched = module().patch_linked_js(LINKED)
        for source in (patched, LINKED.replace("navigator.getGamepads()", "navigator.getGamepads?.()")):
            with self.assertRaisesRegex(ValueError, "MKXP_GAMEPAD_SOURCE_INVALID"):
                module().patch_linked_js(source)


if __name__ == "__main__":
    unittest.main()
