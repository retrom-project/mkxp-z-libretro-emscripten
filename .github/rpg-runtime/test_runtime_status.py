"""Behavior and source-boundary regressions for the threaded browser status ABI."""

from __future__ import annotations

import ctypes
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


RECIPE = Path(__file__).resolve().parent
ROOT = RECIPE.parents[1]


def patch_module():
    spec = importlib.util.spec_from_file_location("patch_status", RECIPE / "patch-runtime-status.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimeStatusTests(unittest.TestCase):
    def test_game_exception_remains_observable_after_opening_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "status.so"
            subprocess.run([
                "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
                str(RECIPE / "runtime-status.c"), "-o", str(output),
            ], check=True, capture_output=True)
            status = ctypes.CDLL(str(output))
            self.assertEqual(status.runtime_get_game_result(), 0)
            status.runtime_frame_presented()
            status.runtime_game_failed()
            status.runtime_frame_presented()
            self.assertEqual(status.runtime_get_frame_count(), 2)
            self.assertEqual(status.runtime_get_game_result(), -1)
            status.runtime_state_finished(True)
            self.assertEqual(status.runtime_get_game_result(), -1)

    def test_browser_exit_only_requests_teardown_on_the_core_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "status.so"
            subprocess.run([
                "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
                str(RECIPE / "runtime-status.c"), "-o", str(output),
            ], check=True, capture_output=True)
            status = ctypes.CDLL(str(output))
            self.assertEqual(status.runtime_take_exit_request(), 0)
            status.runtime_request_exit()
            status.runtime_request_exit()
            self.assertEqual(status.runtime_take_exit_request(), 1)
            self.assertEqual(status.runtime_take_exit_request(), 0)

    def test_exit_is_consumed_before_hidden_paused_or_graphics_loop_work(self):
        source = (ROOT / "retroarch/retroarch.c").read_text(encoding="utf-8")
        patch = patch_module()
        patched = patch.patch_mainloop(source)
        loop = patched.split("void emscripten_mainloop(void)", 1)[1]
        self.assertLess(loop.index("runtime_take_exit_request()"), loop.index("config_get_ptr()"))
        self.assertLess(loop.index("main_exit(NULL)"), loop.index("emscripten_force_exit(0)"))
        self.assertLess(loop.index("emscripten_force_exit(0)"), loop.index("platform_emscripten_should_drop_iter()"))
        with self.assertRaises(ValueError):
            patch.patch_mainloop(patched)
        with self.assertRaises(ValueError):
            patch.patch_mainloop(source.replace("void emscripten_mainloop(void)", "void drift(void)"))

    def test_frames_do_not_report_a_restore_and_failures_do_not_report_success(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "status.so"
            subprocess.run([
                "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
                str(RECIPE / "runtime-status.c"), "-o", str(output),
            ], check=True, capture_output=True)
            status = ctypes.CDLL(str(output))
            self.assertEqual(status.runtime_get_frame_count(), 0)
            self.assertEqual(status.runtime_get_state_result(), 0)
            status.runtime_frame_presented()
            status.runtime_frame_presented()
            self.assertEqual(status.runtime_get_frame_count(), 2)
            self.assertEqual(status.runtime_get_state_result(), 0)
            status.runtime_state_finished(False)
            self.assertEqual(status.runtime_get_state_result(), -1)
            status.runtime_request_state(2)
            self.assertEqual(status.runtime_get_state_result(), 0)
            status.runtime_state_finished(True)
            self.assertEqual(status.runtime_get_state_result(), 1)

    def test_only_completed_deserialization_reports_success(self):
        source = (ROOT / "retroarch/tasks/task_save.c").read_text(encoding="utf-8")
        patched = patch_module().patch_save(source)
        callback = patched.split("static void content_load_state_cb(", 1)[1].split(
            "static void save_state_cb(", 1
        )[0]
        self.assertLess(callback.index("ret = content_deserialize_state"),
                        callback.index("runtime_state_finished(true)"))
        self.assertLess(callback.index("if (!ret)"), callback.index("runtime_state_finished(true)"))
        self.assertLess(callback.rindex("free(load_data);", 0, callback.index("runtime_state_finished(true)")),
                        callback.index("runtime_state_finished(true)"))
        self.assertIn("if (!(load_data->flags & SAVE_TASK_FLAG_LOAD_TO_BACKUP_BUFF))", callback)
        self.assertIn("runtime_state_finished(false)", callback.split("error:", 1)[1])
        request = patched.split("bool content_load_state(const char *path,", 1)[1].split(
            "bool content_rename_state(", 1
        )[0]
        self.assertIn("runtime_state_finished(false)", request.split("error:", 1)[1])

    def test_frame_status_is_written_after_presenting_a_real_core_frame(self):
        source = (ROOT / "retroarch/gfx/video_driver.c").read_text(encoding="utf-8")
        patched = patch_module().patch_video(source)
        self.assertIn("render_frame && data && (video_st->flags & VIDEO_FLAG_ACTIVE)", patched)
        self.assertIn("runloop_st->current_core_type == CORE_TYPE_PLAIN", patched)
        self.assertLess(patched.index("video_st->frame_count++;"),
                        patched.index("runtime_frame_presented();"))

    def test_status_patch_rejects_drift_and_reapplication(self):
        source = (ROOT / "retroarch/tasks/task_save.c").read_text(encoding="utf-8")
        patch = patch_module()
        with self.assertRaises(ValueError):
            patch.patch_save(source.replace("content_deserialize_state(buf, _len)", "changed()"))
        with self.assertRaises(ValueError):
            patch.patch_save(patch.patch_save(source))

    def test_linker_caps_build_parallelism_without_removing_runtime_flags(self):
        source = (ROOT / "retroarch/Makefile.emscripten").read_text(encoding="utf-8")
        patch = patch_module()
        result = patch.patch_linker(source)
        self.assertTrue(result.startswith(source))
        self.assertIn("LDFLAGS += -Wl,--threads=1,--lto-O2", result)
        self.assertIn("export BINARYEN_CORES=2", result)
        self.assertIn("LDFLAGS += -pthread", result)
        self.assertIn("--emit-symbol-map", result)
        with self.assertRaises(ValueError):
            patch.patch_linker(result)


if __name__ == "__main__":
    unittest.main()
