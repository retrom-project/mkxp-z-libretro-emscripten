import importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('patch',ROOT/'patch-remote-content.py')
patch=importlib.util.module_from_spec(spec);spec.loader.exec_module(patch)
class ContentContract(unittest.TestCase):
 def test_transport_and_manifest_are_capability_only(self):
  library=(ROOT/'content-io/libwasmfs_content.js').read_text()
  self.assertNotIn('fetch(',library)
  self.assertNotIn('JSMemoryRanges',library)
  self.assertIn('retrom_content_read_bridge',library)
  self.assertIn('retrom_content_get_size',library)
  platform=patch.patch_retroarch((ROOT.parent.parent/'retroarch/frontend/drivers/platform_emscripten.c').read_text())
  self.assertIn('retrom_content_mount_manifest',platform)
  self.assertNotIn('wasmfs_create_fetch_backend(base_url',platform)
 def test_sdk_thread_fix_is_retained(self):
  self.assertLess(patch.NEW_WORKER_MEMBERS.index('std::mutex'),patch.NEW_WORKER_MEMBERS.index('std::thread'))
if __name__=='__main__': unittest.main()
