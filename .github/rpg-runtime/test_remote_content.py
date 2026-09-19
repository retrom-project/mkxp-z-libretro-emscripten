"""Locked SDK transport replacement and drift guards."""
import importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("patch",ROOT/"patch-remote-content.py")
patch=importlib.util.module_from_spec(spec);spec.loader.exec_module(patch)
class RemoteContent(unittest.TestCase):
 def test_capability_manifest_replaces_url_manifest(self):
  source=(ROOT.parents[1]/"retroarch/frontend/drivers/platform_emscripten.c").read_text()
  result=patch.patch_retroarch(source)
  self.assertIn("retrom_content_mount_manifest",result)
  self.assertNotIn("FETCH_CHUNK_SIZE_BYTES",result)
  self.assertNotIn("base_url[len-1]",result)
  with self.assertRaises(ValueError):patch.patch_retroarch(result)
  with self.assertRaises(ValueError):patch.patch_retroarch(source.replace("16*1024*1024","1"))
 def test_sdk_hash_rejects_drift_and_reapplication(self):
  with self.assertRaises(ValueError):patch.patch_emscripten("changed SDK")
  with self.assertRaises(ValueError):patch.patch_emscripten((ROOT/"content-io/libwasmfs_content.js").read_text())
 def test_native_objects_are_compiled_for_the_threaded_link(self):
  source=(ROOT.parents[1]/"retroarch/Makefile.emscripten").read_text()
  result=patch.patch_makefile(source)
  self.assertIn("CXXFLAGS += -pthread -s SHARED_MEMORY",result)
  self.assertIn("CXXFLAGS += -std=c++17 -O3",result)
  self.assertIn("$(OBJDIR)/frontend/drivers/retrom-content-bridge.o",result)
  with self.assertRaises(ValueError):patch.patch_makefile(result)
 def test_no_transport_or_private_byte_cache_remains(self):
  source=(ROOT/"content-io/libwasmfs_content.js").read_text()
  for token in ("fetch(","JSMemoryRanges","Content-Range","XMLHttpRequest"):self.assertNotIn(token,source)
  self.assertIn("Math.floor(at / 4294967296)",source)
  self.assertIn("Math.min(262144",source)
if __name__=="__main__":unittest.main()
