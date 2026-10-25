"""Native regressions for bounded, completed browser state I/O."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

RECIPE = Path(__file__).resolve().parent
ROOT = RECIPE.parents[1]


def patcher():
    spec = importlib.util.spec_from_file_location("status", RECIPE / "patch-runtime-status.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def save_function(source):
    start = source.index("bool content_auto_save_state(const char *path)")
    end = source.index("/**\n * content_save_state:", start)
    return source[start:end]


class StateIOTests(unittest.TestCase):
    def test_release_verifier_requires_current_state_abi_and_rejects_legacy_or_partial_exports(self):
        spec = importlib.util.spec_from_file_location("verify", RECIPE / "verify-release.py")
        verify = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verify)
        required = [b"_runtime_get_frame_count", b"_runtime_request_exit",
                    b"_runtime_get_state_result", b"_runtime_get_game_result", b"_runtime_request_state"]
        verify.validate_browser_abi(b" ".join(required))
        for missing in required:
            with self.assertRaisesRegex(ValueError, "RPG_RUNTIME_RELEASE_STATE_ABI_INVALID"):
                verify.validate_browser_abi(b" ".join(value for value in required if value != missing)
                                            + b" _runtime_get_restore_result")

    def test_state_commands_use_the_owner_loop_and_completed_blocking_writer(self):
        source = (ROOT / "retroarch/retroarch.c").read_text()
        patched = patcher().patch_mainloop(source)
        loop = patched.split("void emscripten_mainloop(void)", 1)[1]
        self.assertLess(loop.index("runtime_take_exit_request()"), loop.index("runtime_take_state_request()"))
        self.assertLess(loop.index("runtime_take_state_request()"), loop.index("platform_emscripten_should_drop_iter()"))
        self.assertIn("runtime_state_finished(content_auto_save_state(path));", loop)
        self.assertIn("command_event_main_state(CMD_EVENT_LOAD_STATE)", loop)
        with self.assertRaises(ValueError):
            patcher().patch_mainloop(patched)

    def test_raw_state_preallocation_avoids_geometric_growth_and_checks_io_errors(self):
        source = (ROOT / "retroarch/tasks/task_save.c").read_text()
        patched = patcher().patch_save(source)
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / "actual-save.inc").write_text(save_function(patched))
            output = work / "test"
            compiled = subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            "-DEMSCRIPTEN", "-DHAVE_ZLIB", "-I", str(work),
                            str(RECIPE / "test-state-io.cpp"), "-o", str(output)],
                           capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(output)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_browser_requests_are_consumed_only_on_the_core_loop(self):
        import ctypes
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "status.so"
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
                            str(RECIPE / "runtime-status.c"), "-o", str(output)],
                           check=True, capture_output=True)
            status = ctypes.CDLL(str(output))
            self.assertEqual(status.runtime_request_state(9), 0)
            for operation, success in ((1, True), (2, False), (1, True)):
                self.assertEqual(status.runtime_request_state(operation), 1)
                self.assertEqual(status.runtime_get_state_result(), 0)
                self.assertEqual(status.runtime_request_state(operation), 0)
                self.assertEqual(status.runtime_take_state_request(), operation)
                self.assertEqual(status.runtime_take_state_request(), 0)
                self.assertEqual(status.runtime_request_state(operation), 0)
                status.runtime_state_finished(success)
                self.assertEqual(status.runtime_get_state_result(), 1 if success else -1)


if __name__ == "__main__":
    unittest.main()
