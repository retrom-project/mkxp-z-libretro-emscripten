"""Force a new FetchFS worker to run before its thread constructor returns."""

import importlib.util
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RECIPE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("remote", RECIPE / "patch-remote-content.py")
PATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCH)

# The member declarations are the exact pinned SDK patch boundary. The small
# constructor runs the same ready handshake under a controlled early schedule.
SOURCE = """namespace emscripten {
class ProxyWorker {
  ProxyingQueue queue;
  std::thread thread;

  // Used to notify the calling thread once the worker has been started.
  bool started = false;
  std::mutex mutex;
  std::condition_variable cond;

public:
  ProxyWorker() : queue(), thread([&]() {
    { std::unique_lock<std::mutex> lock(mutex); started = true; }
    cond.notify_all();
  }) {
    std::unique_lock<std::mutex> lock(mutex);
    cond.wait(lock, [&]() { return started; });
  }
};
}
"""


def run_handshake(source):
    # Only scheduling and synchronization are replaced. Member order and the
    # constructor body remain the source under test, including in the SDK run.
    body = re.sub(r"^#(?:include|pragma).*\n", "", source, flags=re.MULTILINE)
    for old, new in (("std::thread", "ImmediateThread"), ("std::mutex", "CheckedMutex"),
                     ("std::condition_variable", "CheckedCondition"), ("pthread_cancel", "cancelThread")):
        body = body.replace(old, new)
    program = (RECIPE / "test-thread-startup.cpp").read_text().replace("// SDK_SOURCE", body)
    with tempfile.TemporaryDirectory() as temporary:
        binary = Path(temporary) / "worker"
        compiled = subprocess.run(
            ["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-x", "c++", "-", "-o", str(binary)],
            input=program, text=True, capture_output=True, timeout=30,
        )
        if compiled.returncode:
            raise AssertionError(compiled.stderr)
        return subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)


class ThreadStartupTests(unittest.TestCase):
    def test_immediate_worker_sees_constructed_synchronization_and_retains_ready(self):
        patcher = getattr(PATCH, "patch_thread_utils", lambda value: value)
        result = run_handshake(patcher(SOURCE))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_patch_rejects_drift_and_reapplication(self):
        patcher = getattr(PATCH, "patch_thread_utils", lambda value: value)
        with self.assertRaisesRegex(ValueError, "RPG_RUNTIME_FETCHFS_THREAD_INITIALIZATION_INVALID"):
            patcher(SOURCE.replace("bool started = false;", "bool started = true;"))
        with self.assertRaisesRegex(ValueError, "RPG_RUNTIME_FETCHFS_THREAD_INITIALIZATION_INVALID"):
            patcher(patcher(SOURCE))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--sdk-header":
        result = run_handshake(Path(sys.argv[2]).read_text())
        if result.returncode:
            raise SystemExit(result.stderr)
    else:
        unittest.main()
