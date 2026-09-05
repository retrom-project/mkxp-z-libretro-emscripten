"""The same pristine source contract is verified inside and outside the builder."""

import importlib.util
from pathlib import Path
import runpy
import unittest


RECIPE = Path(__file__).resolve().parent
ROOT = RECIPE.parents[1]
SPEC = importlib.util.spec_from_file_location("verify_release", RECIPE / "verify-release.py")
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)
PATCH_FILE = RECIPE / "patch-remote-content.py"
MARKERS = (b"FETCHFS_RANGE_REQUIRED", b"FETCHFS_RANGE_PROTOCOL_INVALID", b"FETCHFS_RANGE_LENGTH_INVALID")


class ReleaseSourceTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / "retroarch/frontend/drivers/platform_emscripten.c").read_text()
        self.javascript = b" ".join(MARKERS)

    def test_pristine_checkout_and_compiled_range_markers_are_accepted(self):
        self.assertNotIn("FETCH_CHUNK_SIZE_BYTES", self.source)
        VERIFY.validate_remote_content(self.source, self.javascript, PATCH_FILE)

    def test_missing_compiled_range_guards_are_rejected(self):
        for marker in MARKERS:
            with self.subTest(marker=marker), self.assertRaisesRegex(ValueError, "REMOTE_CONTENT_INVALID"):
                VERIFY.validate_remote_content(self.source, self.javascript.replace(marker, b""), PATCH_FILE)

    def test_source_drift_and_already_patched_sources_are_rejected(self):
        patch = runpy.run_path(str(PATCH_FILE))
        for source in (self.source.replace(patch["OLD_BACKEND"], "changed_backend();"),
                       patch["patch_retroarch"](self.source)):
            with self.subTest(source=source[:80]), self.assertRaises(ValueError):
                VERIFY.validate_remote_content(source, self.javascript, PATCH_FILE)

    def test_builder_verifies_its_pristine_input_not_the_mutated_compiler_copy(self):
        builder = (RECIPE / "build-web.sh").read_text()
        verification = builder.split('python3 "$source_root/.github/rpg-runtime/verify-release.py"', 1)[1]
        verification = verification.split("\n}", 1)[0]
        self.assertIn('--source "$root"', verification)
        self.assertNotIn('--source "$source_root"', verification)


if __name__ == "__main__":
    unittest.main()
