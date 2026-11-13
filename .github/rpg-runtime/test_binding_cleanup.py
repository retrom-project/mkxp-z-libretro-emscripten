"""Exercise the generated C++ binding after Ruby reuses its unwound C stack."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


RECIPE = Path(__file__).resolve().parent
ROOT = RECIPE.parents[1]


def module():
    spec = importlib.util.spec_from_file_location("binding_cleanup", RECIPE / "patch-binding-cleanup.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HARNESS = r'''
#include <boost/asio/coroutine.hpp>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <vector>
using wasm_ptr_t = uint32_t;
using VALUE = uint32_t;
template<typename... T> struct decl_slots {};
struct Ruby { int state = 0; bool yielding = true; };
struct binding_base {
    Ruby ruby;
    uint32_t words[128] = {};
    std::vector<uint32_t> allocated, freed;
    bool fail_second = false;
    Ruby& instance() { return ruby; }
    uint32_t stack_pointer() { return 0; }
    uint32_t sandbox_malloc(size_t) {
        if (fail_second && allocated.size() == 1) return 0;
        uint32_t p = 64 + allocated.size() * 16;
        allocated.push_back(p); return p;
    }
    void sandbox_free(uint32_t p) { freed.push_back(p); }
    void strcpy(uint32_t, const char*) {}
};
int w2c_ruby_asyncify_get_state(Ruby* ruby) { return ruby->state; }
uint32_t w2c_ruby_rb_file_open(Ruby* ruby, uint32_t, uint32_t) {
    ruby->state = ruby->yielding ? 1 : 0;
    return 0;
}
#define MKXPZ_THROW(value) throw value
#define _SBINDGEN_SLOT(index) (bind.words[index])
DECLARATION
IMPLEMENTATION
int main() {
    binding_base bind;
    rb_file_open call(bind);
    call("missing.rvdata2", "rb");
    assert(!call.is_complete());
    // The rescued Ruby code can overwrite these stack slots before the next
    // native callback prunes the now-orphaned C++ coroutine.
    bind.words[0] = 0xdead;
    bind.words[1] = 0xbeef;
    bind.ruby.state = 0;
    call.end();
    assert(bind.freed.size() == 2);
    assert(bind.freed[0] == bind.allocated[1]);
    assert(bind.freed[1] == bind.allocated[0]);

    binding_base partial;
    partial.fail_second = true;
    rb_file_open interrupted(partial);
    try { interrupted("missing.rvdata2", "rb"); assert(false); }
    catch (const std::bad_alloc&) {}
    interrupted.end();
    assert(partial.freed == partial.allocated);

    binding_base normal;
    normal.ruby.yielding = false;
    rb_file_open completed(normal);
    completed("present.rvdata2", "rb");
    assert(completed.is_complete());
    completed.end();
    assert(normal.freed[0] == normal.allocated[1]);
    assert(normal.freed[1] == normal.allocated[0]);

    binding_base original;
    rb_file_open suspended(original);
    suspended("missing.rvdata2", "rb");
    boost::asio::detail::coroutine_ref saved_state(suspended);
    const int state = saved_state;
    saved_state = state;
    binding_base restored;
    restored.allocated = original.allocated;
    std::memcpy(restored.words, original.words, sizeof(original.words));
    rb_file_open resumed(restored);
    // The core serializes coroutine state and sandbox slots, not C++ members.
    {
        boost::asio::detail::coroutine_ref resumed_state(resumed);
        resumed_state = state;
    }
    resumed(nullptr, nullptr);
    restored.words[0] = 0xdead;
    restored.words[1] = 0xbeef;
    restored.ruby.state = 0;
    resumed.end();
    assert(restored.freed[0] == restored.allocated[1]);
    assert(restored.freed[1] == restored.allocated[0]);
}
'''


class BindingCleanupTests(unittest.TestCase):
    def test_generated_file_open_owns_cleanup_after_exception_reuses_slots(self):
        self.assertIsNotNone(shutil.which("ruby"), "Ruby is needed to test the real generator")
        self.assertIsNotNone(shutil.which("g++"), "C++ is needed to execute the generated binding")
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            (work / "generator.rb").write_text((ROOT / "mkxp-z/libretro/sandbox-bindgen.rb").read_text())
            (work / "tags").write_text(
                'rb_file_open\ttags.c\t/^VALUE rb_file_open(const char *fname, const char *mode);$/;"'
                '\tp\tsignature:(const char * fname, const char * mode)\n'
            )
            subprocess.run(["ruby", "-rset", "generator.rb"], cwd=work, check=True, capture_output=True)
            header = (work / "mkxp-sandbox-bindgen.h").read_text()
            implementation = (work / "mkxp-sandbox-bindgen.cpp").read_text()
            header, implementation = module().patch_bindings(header, implementation)
            declaration = re.search(r"    struct rb_file_open :.*?\n    };", header, re.S)
            self.assertIsNotNone(declaration)
            start = implementation.index("rb_file_open::rb_file_open(")
            end = implementation.index("\n\n", implementation.index("void rb_file_open::end()", start))
            methods = implementation[start:end]
            (work / "test.cpp").write_text(HARNESS.replace("DECLARATION", declaration[0]).replace("IMPLEMENTATION", methods))
            compiled = subprocess.run(["g++", "-std=c++17", "-O2", "test.cpp", "-o", "test"], cwd=work, capture_output=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr.decode())
            completed = subprocess.run([str(work / "test")], cwd=work, capture_output=True)
            self.assertEqual(completed.returncode, 0, completed.stderr.decode())

    def test_patch_rejects_reapplying_to_changed_binding_outputs(self):
        patcher = module()
        source = (ROOT / "mkxp-z/binding-sandbox/binding-base.h").read_text()
        patched = patcher.patch_frames(source)
        with self.assertRaisesRegex(ValueError, "MKXP_BINDING_CLEANUP_SOURCE_INVALID"):
            patcher.patch_frames(patched)


if __name__ == "__main__":
    unittest.main()
