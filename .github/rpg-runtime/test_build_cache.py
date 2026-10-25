import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import hashlib


def module():
    spec = importlib.util.spec_from_file_location("build_cache", Path(__file__).with_name("build-cache.py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class BuildCacheTests(unittest.TestCase):
    def test_stage1_key_tracks_source_and_recipe_bytes_but_not_git_metadata(self):
        cache = module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "mkxp-z").mkdir()
            (root / "mkxp-z/ruby.c").write_bytes(b"input")
            recipe = root / ".github/rpg-runtime"
            recipe.mkdir(parents=True)
            for name in ("patch-runtime.py", "mkxp-deterministic-bindings.patch", "patch-ruby.py",
                         "ruby-try-catch-unwind.patch"):
                (recipe / name).write_bytes(b"recipe")
            script = (
                "stage1_image=locked\nemscripten_image=locked\n"
                "build_stage1() {\n  compile stage1\n}\n\n"
                "build_core() {\n  compile core\n}\n\nbuild_frontend() {\n  link\n}\n"
            )
            (recipe / "build-web.sh").write_text(script)
            original = cache.stage1_key(root)
            (root / "mkxp-z/.git").write_bytes(b"host-only metadata")
            self.assertEqual(cache.stage1_key(root), original)
            (root / "mkxp-z/ruby.c").write_bytes(b"changed")
            self.assertNotEqual(cache.stage1_key(root), original)
            (root / "mkxp-z/ruby.c").write_bytes(b"input")
            (recipe / "build-web.sh").write_text(script.replace("link", "bounded link"))
            self.assertEqual(cache.stage1_key(root), original)
            (recipe / "build-web.sh").write_text(script.replace("compile stage1", "new stage1 flags"))
            self.assertNotEqual(cache.stage1_key(root), original)

    def test_ruby_translation_units_do_not_form_a_giant_lto_module(self):
        spec = importlib.util.spec_from_file_location("memory", Path(__file__).with_name("patch-build-memory.py"))
        memory = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(memory)
        source = (Path(__file__).resolve().parents[2] / "mkxp-z/meson.build").read_text()
        result = memory.patch_ruby(source)
        self.assertEqual(result.count("override_options: ['b_lto=false']"), 1)
        self.assertIn("'ruby',\n            override_options: ['b_lto=false'],", result)
        self.assertNotIn("b_lto=false", result.split("'ruby',", 1)[0])
        with self.assertRaises(ValueError):
            memory.patch_ruby(result)

    def test_stage1_reuse_requires_identical_inputs_and_verified_artifacts(self):
        cache = module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, saved = root / "source", root / "cache"
            source.mkdir()
            (source / "ruby.a").write_bytes(b"compiled")
            cache.store_artifacts(source, saved)
            cache.restore_artifacts(saved, root / "restored")
            self.assertEqual((root / "restored/ruby.a").read_bytes(), b"compiled")
            (saved / "files/ruby.a").write_bytes(b"corrupted")
            with self.assertRaisesRegex(ValueError, "MKXP_BUILD_CACHE_INVALID"):
                cache.restore_artifacts(saved, root / "bad")
            self.assertFalse((root / "bad").exists())

    def test_wrap_uses_locked_hash_and_gnu_origin_without_redownloading(self):
        cache = module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wrap = root / "libiconv.wrap"
            content = b"verified archive"
            wrap.write_text("[wrap-file]\nsource_url = https://ftpmirror.gnu.org/libiconv/libiconv-1.18.tar.gz\n"
                            "source_filename = libiconv.tar.gz\nsource_hash = " + hashlib.sha256(content).hexdigest())
            with patch.object(cache.urllib.request, "urlopen", side_effect=lambda *a, **k: io.BytesIO(content)) as fetch:
                cache.cache_wrap(wrap, root / "downloads")
                cache.cache_wrap(wrap, root / "downloads")
                fetch.assert_called_once_with("https://ftp.gnu.org/gnu/libiconv/libiconv-1.18.tar.gz", timeout=30)
            (root / "downloads/libiconv.tar.gz").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "MKXP_DEPENDENCY_HASH_INVALID"):
                cache.cache_wrap(wrap, root / "downloads")

    def test_wrap_never_publishes_bad_downloads(self):
        cache = module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wrap = root / "bad.wrap"
            wrap.write_text("[wrap-file]\nsource_url = https://example.invalid/archive\n"
                            "source_filename = archive.tar.gz\nsource_hash = " + "a" * 64)
            with patch.object(cache.urllib.request, "urlopen", return_value=io.BytesIO(b"bad")):
                with self.assertRaisesRegex(ValueError, "MKXP_DEPENDENCY_HASH_INVALID"):
                    cache.cache_wrap(wrap, root / "downloads")
            self.assertFalse((root / "downloads/archive.tar.gz").exists())


if __name__ == "__main__":
    unittest.main()
