"""Check that the WASI Ruby clone receives the reviewed asyncify fix."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


RECIPE = Path(__file__).resolve().parent
ROOT = RECIPE.parents[1]


def module():
    spec = importlib.util.spec_from_file_location("ruby_patch", RECIPE / "patch-ruby.py")
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


class RubyPatchTests(unittest.TestCase):
    def test_ruby_clone_applies_recipe_patches_before_bindings_are_appended(self):
        source = (ROOT / "mkxp-z/libretro/Makefile").read_text()
        patched = module().patch_makefile(source, RECIPE)
        clone = patched.split("$(RUBY_SRC)/configure.ac:\n", 1)[1]
        line = f"\tcd $(RUBY_SRC) && $(GIT) apply {RECIPE / 'ruby-try-catch-unwind.patch'}\n"
        self.assertLess(clone.index("ruby-prng-time.patch"), clone.index(line))
        self.assertLess(clone.index(line), clone.index("ruby-bindings.h"))
        self.assertIn("RUBY_VERSION ?= 3.3.10\n", source)
        with self.assertRaisesRegex(ValueError, "MKXP_RUBY_PATCH_SOURCE_INVALID"):
            module().patch_makefile(patched, RECIPE)

    def test_caught_longjmp_clears_the_root_unwind_marker(self):
        # mkxp's host yield unwinds without rb_asyncify_unwind_buf; a stale value
        # made the root loop rewind an empty thread buffer after a rescued fiber exception.
        patch = (RECIPE / "ruby-try-catch-unwind.patch").read_text()
        self.assertIn("+++ b/wasm/setjmp.c\n", patch)
        hunk = patch.split("@@", 2)[2]
        added = [line for line in hunk.splitlines() if line.startswith("+")]
        self.assertIn("+            rb_asyncify_unwind_buf = NULL;", added)
        self.assertLess(hunk.index(" asyncify_stop_rewind();"), hunk.index("+            rb_asyncify_unwind_buf = NULL;"))


if __name__ == "__main__":
    unittest.main()
