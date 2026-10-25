"""Execute the patched upstream font selector and ZIP stat with native probes."""

from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


RECIPE = Path(__file__).resolve().parent
ROOT = RECIPE.parents[1]
PHYSFS_SHA256 = "54ee8b286ba18333894bb27855f3fafa5c1a59d012b8115c1c5f21c06a2f064a"


def startup_patch(source: str, function: str) -> str:
    path = RECIPE / "patch-startup.py"
    if not path.exists() or os.environ.get("MKXP_TEST_UNPATCHED") == "1":
        return source
    spec = importlib.util.spec_from_file_location("startup", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, function)(source)


def compile_and_run(source: str, *, cpp: bool = False) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        path = root / ("probe.cpp" if cpp else "probe.c")
        path.write_text(source, encoding="utf-8")
        subprocess.run([
            "c++" if cpp else "cc", "-std=c++17" if cpp else "-std=c11",
            "-Wall", "-Wextra", "-Werror", str(path), "-o", str(root / "probe"),
        ], check=True, capture_output=True)
        result = subprocess.run([str(root / "probe")], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr or result.stdout)


class StartupTests(unittest.TestCase):
    def test_core_publishes_exception_before_destroying_the_game_sandbox(self):
        source = (ROOT / "mkxp-z/src/core.cpp").read_text()
        patched = startup_patch(source, "patch_core")
        fatal = patched.split("Game threw an exception; terminating", 1)[1]
        self.assertLess(fatal.index("runtime_game_failed();"), fatal.index("deinit_sandbox();"))
        self.assertIn('extern "C" void runtime_game_failed(void);', patched)

    def test_forced_assertion_publishes_game_failure_before_aborting(self):
        patched = startup_patch((ROOT / "mkxp-z/src/util/forced-assert.h").read_text(), "patch_forced_assert")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "forced-assert.h").write_text(patched)
            (root / "libretro.h").write_text(
                "enum retro_log_level { RETRO_LOG_ERROR = 3 };\n"
                "typedef void (*retro_log_printf_t)(enum retro_log_level, const char *, ...);\n")
            (root / "probe.cpp").write_text(r'''
#include <csignal>
#include <unistd.h>
#include "forced-assert.h"
static volatile int failed;
static void ignore_log(enum retro_log_level, const char *, ...) {}
retro_log_printf_t mkxp_retro_log_printf = ignore_log;
extern "C" void runtime_game_failed(void) { failed = 1; }
int main() {
  std::signal(SIGABRT, [](int) { _exit(failed ? 0 : 2); });
  MKXPZ_FORCED_ASSERT_WITH_MESSAGE(false, "Sandbox trap");
  return 3;
}
''')
            subprocess.run(["c++", "-std=c++17", "-Wall", "-Werror", "-DMKXPZ_RETRO", "-D__EMSCRIPTEN__",
                            "-I", str(root), str(root / "probe.cpp"), "-o", str(root / "probe")],
                           check=True, capture_output=True)
            self.assertEqual(subprocess.run([str(root / "probe")], capture_output=True).returncode, 0)

    def test_libretro_keyboard_uses_desktop_rgss_default_bindings(self):
        patched = startup_patch((ROOT / "mkxp-z/src/input/input-retro.cpp").read_text(), "patch_keyboard")
        update = patched.split("void updateButtonStates()", 1)[1].split("void updateDir4()", 1)[0]
        desktop = (ROOT / "mkxp-z/src/input/keybindings.cpp").read_text()

        def retrok(scancode: str) -> str:
            return "RETROK_" + ("KP0" if scancode == "KP_0" else scancode.lower() if len(scancode) == 1 else scancode)

        common = desktop.split("defaultKbBindings[] =", 1)[1].split("};", 1)[0]
        for scancode, button in re.findall(r"SDL_SCANCODE_(\w+),\s*(Input::\w+)", common):
            self.assertIn(f"{{{retrok(scancode)}, {button}}}", update)
        self.assertIn("buttonStates[Input::A] || keyboardStates[RETROK_z]", update.split("} else {", 1)[0])
        self.assertIn("buttonStates[Input::C] || keyboardStates[RETROK_c]", update.split("} else {", 1)[0])
        self.assertIn("buttonStates[Input::C] || keyboardStates[RETROK_z]", update.split("} else {", 1)[1])

    def test_patch_recipe_rejects_source_drift_and_reapplication(self):
        for relative, function in (("src/display/font.cpp", "patch_font"), ("src/core.cpp", "patch_core"),
                                   ("src/util/forced-assert.h", "patch_forced_assert"),
                                   ("src/input/input-retro.cpp", "patch_keyboard")):
            source = (ROOT / "mkxp-z" / relative).read_text()
            patched = startup_patch(source, function)
            with self.assertRaisesRegex(ValueError, "MKXP_STARTUP_SOURCE_INVALID"):
                startup_patch(patched, function)

    def test_localized_sfnt_names_open_the_registered_font_path(self):
        source = (ROOT / "mkxp-z/src/display/font.cpp").read_text()
        source = startup_patch(source, "patch_font")
        font_set = source.split("struct FontSet\n", 1)[1].split("struct SharedFontStatePrivate", 1)[0]
        branch = source.split("/* Not in pool; open new handle */", 1)[1]
        selector = re.search(r"const char \*path =[^;]+;", branch).group()
        compile_and_run('''
#include <cstdio>
#include <string>
struct FontSet
''' + font_set + '''
static const char *select_path(const FontSet &req) {''' + selector + ''' return path; }
int main() {
  for (const bool regular : {false, true}) {
    FontSet alias;
    (regular ? alias.sfnt_regular : alias.sfnt_other) = "/Game/Fonts/localized.ttf";
    if (std::string(select_path(alias)) != "/Game/Fonts/localized.ttf") {
      std::fputs("localized family is registered but opens an empty font path\\n", stderr);
      return 1;
    }
  }
  FontSet fonts;
  fonts.other = "other.ttf"; fonts.regular = "regular.ttf";
  fonts.sfnt_other = "sfnt-other.ttf"; fonts.sfnt_regular = "sfnt-regular.ttf";
  if (std::string(select_path(fonts)) != *fonts.operator->()) return 2;
}
''', cpp=True)

    def test_directory_metadata_does_not_read_every_zip_local_header(self):
        path = Path(os.environ.get("MKXP_PHYSFS_SOURCE_PATH", ROOT / ".cache/test-inputs/physfs_archiver_zip.c"))
        source = path.read_text()
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), PHYSFS_SHA256)
        patched = startup_patch(source, "patch_zip")
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / "src/physfs_archiver_zip.c"
            file.parent.mkdir()
            file.write_text(source)
            subprocess.run(["git", "apply", str(RECIPE / "physfs-metadata-stat.patch")],
                           cwd=temporary, check=True, capture_output=True)
            self.assertEqual(file.read_text(), patched)
        function = patched.split("static int ZIP_stat(", 1)[1].split("} /* ZIP_stat */", 1)[0]
        enum = source.split("typedef enum\n", 1)[1].split("} ZipResolveType;", 1)[0]
        resolve = source.split("static int zip_resolve(PHYSFS_Io *io, ZIPinfo *info, ZIPentry *entry)\n{", 1)[1].split("} /* zip_resolve */", 1)[0]
        is_symlink = source.split("static int zip_entry_is_symlink(const ZIPentry *entry)\n{", 1)[1].split("} /* zip_entry_is_symlink */", 1)[0]
        compile_and_run('''
#include <stdio.h>
#include <string.h>
typedef long long PHYSFS_sint64;
typedef enum
''' + enum + '''} ZipResolveType;
typedef struct ZIPentry {
  struct {int isdir;} tree;
  struct ZIPentry *symlink;
  ZipResolveType resolved;
  unsigned long long uncompressed_size;
  long long last_mod_time;
} ZIPentry;
typedef void PHYSFS_Io;
typedef struct {PHYSFS_Io *io;} ZIPinfo;
typedef struct {long long filesize, modtime, createtime, accesstime; int readonly, filetype;} PHYSFS_Stat;
enum {PHYSFS_FILETYPE_DIRECTORY, PHYSFS_FILETYPE_SYMLINK, PHYSFS_FILETYPE_REGULAR};
static ZIPentry entry;
static int local_reads;
static ZIPentry *zip_find_entry(ZIPinfo *info, const char *name) {(void)info; return strcmp(name,"missing") ? &entry : NULL;}
enum {PHYSFS_ERR_CORRUPT, PHYSFS_ERR_SYMLINK_LOOP};
#define BAIL_IF(condition,error,result) do {if(condition) return result;} while(0)
static int zip_parse_local(PHYSFS_Io *io, ZIPentry *item) {(void)io; (void)item; local_reads++; return 1;}
static ZIPentry link_target;
static int zip_resolve_symlink(PHYSFS_Io *io, ZIPinfo *info, ZIPentry *item) {(void)io; (void)info; item->symlink=&link_target; return 1;}
static int zip_resolve(PHYSFS_Io *io, ZIPinfo *info, ZIPentry *entry) {''' + resolve + '''}
static int zip_entry_is_symlink(const ZIPentry *entry) {''' + is_symlink + '''}
static int ZIP_stat(''' + function + '''}
int main(void) {
  ZIPinfo archive = {0}; PHYSFS_Stat stat;
  entry.resolved = ZIP_UNRESOLVED_FILE;
  entry.uncompressed_size = 4000000000ULL; entry.last_mod_time = 123;
  for (int i=0;i<955;i++) {
    if (!ZIP_stat(&archive,"asset",&stat)) return 2;
  }
  if (local_reads) {fprintf(stderr,"directory traversal read %d local headers\\n",local_reads); return 1;}
  if (stat.filesize != 4000000000LL || stat.filetype != PHYSFS_FILETYPE_REGULAR || stat.modtime != 123 || !stat.readonly) return 3;
  if (ZIP_stat(&archive,"missing",&stat)) return 4;
  entry.resolved = ZIP_UNRESOLVED_SYMLINK;
  if (!ZIP_stat(&archive,"link",&stat) || local_reads != 1 || stat.filetype != PHYSFS_FILETYPE_SYMLINK) return 5;
  entry.resolved = ZIP_BROKEN_FILE;
  if (ZIP_stat(&archive,"broken",&stat)) return 6;
  entry.resolved = ZIP_DIRECTORY;
  if (!ZIP_stat(&archive,"dir",&stat) || stat.filetype != PHYSFS_FILETYPE_DIRECTORY || stat.filesize != 0) return 7;
  entry.symlink = NULL; entry.tree.isdir = 1; entry.resolved = ZIP_UNRESOLVED_FILE;
  if (!ZIP_stat(&archive,"implicit-dir",&stat) || stat.filetype != PHYSFS_FILETYPE_DIRECTORY || local_reads != 1) {
    fputs("implicit ZIP parent is classified as a file; directory traversal stops\\n",stderr); return 8;
  }
}
''')
        # Opening file bytes must retain the original local-header validation.
        before_open = source.split("static PHYSFS_Io *ZIP_openRead(", 1)[1].split("} /* ZIP_openRead */", 1)[0]
        after_open = patched.split("static PHYSFS_Io *ZIP_openRead(", 1)[1].split("} /* ZIP_openRead */", 1)[0]
        self.assertEqual(before_open, after_open)


if __name__ == "__main__":
    unittest.main()
