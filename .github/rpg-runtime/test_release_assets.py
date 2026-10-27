"""Downloaded build assets retain their original identity and integrity receipt."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("verify_assets", Path(__file__).with_name("verify-release.py"))
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


class ReleaseAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name)
        contract_hash = (ROOT / ".github/rpg-runtime/content-io/v1/CONTRACT.sha256").read_text().split()[0]
        javascript = " ".join((
            "retromContentBridge", "content-io-v1", "readIntoById", contract_hash,
            "_runtime_get_frame_count", "_runtime_get_state_result", "_runtime_get_game_result",
            "_runtime_request_state", "_runtime_request_exit",
        )).encode().ljust(200_000, b" ")
        (self.output / "mkxp-z_libretro.js").write_bytes(javascript)
        with (self.output / "mkxp-z_libretro.wasm").open("wb") as wasm:
            wasm.write(b"\x00asm\x01\x00\x00\x00")
            wasm.truncate(40_000_000)
        self.manifest = self.output / "rpg-runtime-release.json"

    def verify(self, *arguments):
        with patch("sys.argv", [
            "verify-release.py", "--source", str(ROOT), "--output", str(self.output),
            "--repository", "https://github.com/retrom-project/mkxp-z-libretro-emscripten",
            "--tag", "retrom-core-f2efc98-r999999", "--commit", "a" * 40, *arguments,
        ]):
            return VERIFY.main()

    def test_downloaded_pair_is_checked_without_rewriting_the_manifest(self):
        self.assertEqual(self.verify(), 0)
        self.manifest.write_text(json.dumps(json.loads(self.manifest.read_text())) + "\n")
        original = self.manifest.read_bytes()
        self.assertEqual(self.verify("--check-existing"), 0)
        self.assertEqual(self.manifest.read_bytes(), original)

    def test_changed_download_is_rejected_without_replacing_its_receipt(self):
        self.verify()
        original = self.manifest.read_bytes()
        with (self.output / "mkxp-z_libretro.js").open("r+b") as javascript:
            javascript.seek(-1, 2)
            javascript.write(b"!")
        with self.assertRaisesRegex(SystemExit, "RPG_RUNTIME_RELEASE_ASSETS_CHANGED"):
            self.verify("--check-existing")
        self.assertEqual(self.manifest.read_bytes(), original)

    def test_mismatched_release_identity_and_abi_are_rejected(self):
        self.verify()
        original = json.loads(self.manifest.read_text())
        for field, value in (("commit", "b" * 40), ("tag", "retrom-core-f2efc98-r1"),
                             ("repository", "https://example.invalid/fork"), ("adapterAbi", "wrong")):
            with self.subTest(field=field):
                changed = dict(original, **{field: value})
                self.manifest.write_text(json.dumps(changed))
                with self.assertRaisesRegex(SystemExit, "RPG_RUNTIME_RELEASE_ASSETS_CHANGED"):
                    self.verify("--check-existing")

    def test_missing_receipt_is_rejected_instead_of_regenerated(self):
        with self.assertRaisesRegex(SystemExit, "RPG_RUNTIME_RELEASE_METADATA_INVALID"):
            self.verify("--check-existing")
        self.assertFalse(self.manifest.exists())


if __name__ == "__main__":
    unittest.main()
