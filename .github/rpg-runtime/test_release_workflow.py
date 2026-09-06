import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
CHECKPOINT = "bf5f525e864b162bea0789d46932e5f800b80076"


class ReleaseWorkflowTests(unittest.TestCase):
    def test_quality_prepares_all_locked_fetchfs_sources_and_checks_worker_startup(self) -> None:
        workflow = (ROOT / ".github/workflows/rpg-runtime-quality.yml").read_text()
        for source in ("src/lib/libwasmfs_fetch.js", "system/lib/wasmfs/backends/fetch_backend.cpp",
                       "system/lib/wasmfs/thread_utils.h"):
            self.assertIn("https://raw.githubusercontent.com/emscripten-core/emscripten/4.0.8/" + source,
                          workflow)
        self.assertIn("test_thread_startup.py", workflow)
        self.assertIn('--sdk-header "${{ runner.temp }}/emscripten/system/lib/wasmfs/thread_utils.h"', workflow)

    def test_upstream_demo_does_not_run_for_retrom_work_branches_or_prs(self) -> None:
        workflow = (ROOT / ".github/workflows/autobuild.yml").read_text()
        triggers = workflow.split("permissions:", 1)[0]
        self.assertIn('push:\n    branches: [main]', triggers)
        self.assertIn('pull_request:\n    branches: [main]', triggers)

    def test_release_uses_the_same_verified_builder_as_pfb(self) -> None:
        workflow = (ROOT / ".github/workflows/rpg-runtime-release.yml").read_text()
        self.assertIn('.github/rpg-runtime/build-web.sh "$output"', workflow)
        self.assertNotIn("emmake make", workflow)
        self.assertNotIn("meson setup", workflow)
        self.assertEqual(workflow.count("uses: actions/checkout@"), 1)
        self.assertLess(workflow.index("build-web.sh"), workflow.index("verify-release.py"))
        self.assertIn('test "$(git cat-file -t "refs/tags/$GITHUB_REF_NAME")" = tag', workflow)

    def test_release_identity_uses_the_organization_and_core_tag_namespace(self) -> None:
        contract = json.loads((ROOT / "retrom-fork.json").read_text(encoding="utf-8"))
        workflow = (ROOT / ".github/workflows/rpg-runtime-release.yml").read_text(encoding="utf-8")

        self.assertEqual(
            contract["forkRepository"],
            "https://github.com/retrom-project/mkxp-z-libretro-emscripten",
        )
        self.assertIn("^retrom-core-(f2efc98|g[0-9a-f]{12})", contract["releaseTagPattern"])
        self.assertIn('"retrom-core-f2efc98-r*"', workflow)
        self.assertNotIn('"rpg-runtime-f2efc98-r*"', workflow)

    def test_release_rejects_merges_after_immutable_checkpoint(self) -> None:
        workflow = (ROOT / ".github/workflows/rpg-runtime-release.yml").read_text(encoding="utf-8")
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

        self.assertIn(f'{CHECKPOINT}.."$GITHUB_SHA"', workflow)
        self.assertIn("git rev-list --min-parents=2", workflow)
        self.assertIn("must\n  use squash merge", agents)
        self.assertIn(CHECKPOINT, agents)

    def test_pfb_candidate_uses_locked_builder_and_calling_user(self) -> None:
        recipe = ROOT / ".github/rpg-runtime"
        candidate = (recipe / "build-candidate.sh").read_text(encoding="utf-8")
        builder = (recipe / "build-web.sh").read_text(encoding="utf-8")

        self.assertIn('candidate_descriptor.py" prepare', candidate)
        self.assertIn('candidate_descriptor.py" finalize', candidate)
        self.assertIn('test -f "$output/rpg-runtime-release.json"', candidate)
        self.assertIn('verify-release.py"', builder)
        self.assertIn('--source "$source_root"', builder)
        self.assertIn('patch-runtime-status.py"', builder)
        self.assertIn('source-snapshot.py" --source "$root" --output "$work/input"', builder)
        self.assertEqual(builder.count('--volume "$source_input:/input:ro"'), 3)
        self.assertIn('build-cache.py" restore', builder)
        self.assertIn('build-cache.py" store', builder)
        self.assertIn("MESON_PACKAGE_CACHE_DIR=/cache", builder)
        self.assertIn("--core-id mkxp", candidate)
        self.assertIn("stage1_image=ubuntu@sha256:", builder)
        self.assertIn("emscripten_image=emscripten/emsdk@sha256:", builder)
        self.assertIn("--stage1-in-container", builder)
        self.assertIn("--core-in-container", builder)
        self.assertIn("--frontend-in-container", builder)
        self.assertIn('"$artifacts/stage1/."', builder)
        self.assertIn('"$artifacts/mkxp-z_libretro.a"', builder)
        self.assertIn("if ((jobs > 4))", builder)
        self.assertIn('find "$work/core" -mindepth 1 -delete', builder)
        self.assertIn("libtool python3 ruby", builder)
        self.assertIn("cmake==3.28.3 meson==1.3.2", builder)
        self.assertIn('setpriv --reuid="$1" --regid="$2"', builder)
        self.assertIn("XDG_CONFIG_HOME=/work/frontend/user-config", builder)
        self.assertIn("c = 'emcc'", builder)
        self.assertNotIn("RUBYOPT=-rset", builder)
        self.assertNotIn("/var/run/docker.sock", builder)

    def test_local_symbols_are_keyed_by_the_output_wasm_not_published_as_assets(self):
        builder = (ROOT / ".github/rpg-runtime/build-web.sh").read_text()
        self.assertIn('sha256sum "$output/mkxp-z_libretro.wasm"', builder)
        self.assertIn('"$cache_root/symbols/$wasm_sha.symbols"', builder)
        self.assertLess(builder.rindex('--frontend-in-container /work/frontend'),
                        builder.index('wasm_sha=$(sha256sum'))
        self.assertNotIn('"$output/mkxp-z_libretro.symbols"', builder)

    def test_frontend_prepares_sdk_ownership_before_dropping_to_the_calling_user(self):
        builder = (ROOT / ".github/rpg-runtime/build-web.sh").read_text()
        frontend = builder.split('--hostname rpg-runtime-mkxp-frontend', 1)[1]
        # The pinned SDK is owned by UID 1000, while CI uses UID 1001. FetchFS
        # patches and the rebuilt system-library cache must work for either.
        ownership = 'chown -R "$1:$2" "$(em-config EMSCRIPTEN_ROOT)"'
        self.assertIn(ownership, frontend)
        self.assertLess(frontend.index(ownership), frontend.index('exec setpriv'))
        self.assertIn('--volume "$source_input:/input:ro"', frontend)
        self.assertNotIn('chown -R "$1:$2" /input', frontend)


if __name__ == "__main__":
    unittest.main()
