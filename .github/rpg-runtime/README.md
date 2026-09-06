# RPG Runtime mkxp-z Web release

Tags matching `retrom-core-f2efc98-rN` build only the pinned mkxp-z core and
RetroArch Emscripten frontend. The workflow never downloads or packages RPG
Maker games or RTP archives.

The release contains:

- `mkxp-z_libretro.js`
- `mkxp-z_libretro.wasm`
- `rpg-runtime-release.json`

Before a tag exists, a maintainer can dispatch the same workflow on a
`feat/*`, `fix/*`, `build/*`, or active `retrom/*` branch. It uploads the JS
and Wasm pair as a seven-day integration artifact without creating a Release.
That candidate is intended for the aggregate runtime's local asset override
and Retrom product-chain validation. Only a tag run validates release metadata
and creates the immutable GitHub Release.

Both tag/dispatch CI and PFB call `build-web.sh`, including its pinned toolchain,
all native patches, bounded-memory stages and verified intermediate cache. CI
checks out the fixed sources once and does not maintain a second compilation
recipe. A tag run revalidates the resulting pair with the actual immutable
release identity before upload; local diagnostic symbol maps are not assets.

The tagged superproject fixes the exact mkxp-z and RetroArch gitlinks. A small
build patch replaces mkxp-z's random sandbox function-type identifiers with
identifiers derived from the function type name. This is required because the
sandbox binding hash is part of the save-state compatibility contract.
The release preparation also guards the post-state-load movie-frame query
against the transient empty sandbox state observed after a successful
libretro `retro_unserialize`; without the guard the next frame aborts before
restored game input can resume.

The browser can read `Module._runtime_get_frame_count()` and
`Module._runtime_get_state_result()` from the main thread without invoking
RetroArch GL commands. Both read atomics maintained by the core thread. Frame
count advances only for presented game-core frames, never RetroArch's dummy
core after a failed content load; state result is zero while
pending, one after success, and minus one on failure.
Frames alone never imply restore success. These observations require no
preload script, map position, fixture variable, or host-provided proof.
They do not alter the mkxp sandbox bindings or the checkpoint format.

`Module._runtime_request_state(1)` requests a save, and operation `2` requests
a restore. The function only atomically publishes intent and returns one when
accepted, zero for an invalid or overlapping request. The owning loop consumes
each request once, including when hidden or paused; a new request clears the
previous receipt atomically. Hosts must not synthesize short-lived save/load
hotkeys or invoke a RetroArch GL command from the browser thread.

Saving uses RetroArch's existing blocking writer on its core thread. For raw
WasmFS states it preallocates the exact RASTATE length before writing. A
power-of-two core payload plus the 24-byte envelope otherwise makes the memory
file's vector double on its final write while retaining the old allocation,
which can exhaust the Wasm heap after restoration. Completion is reported only
after writing, flushing, closing and freeing the serialization buffer; open, truncate,
write, flush and close failures must never report success. File length is not a
completion signal, since preallocation publishes that length before filling
the file. Restore uses the normal RetroArch load path and reports successful
deserialization only after releasing its load buffer. Hosts remove temporary
state files after consuming the corresponding receipt. Native tests execute
the actual patched writer with a bounded allocator, exact byte verification
and each I/O failure; compressed states retain their existing behavior.

`Module._runtime_request_exit()` publishes an atomic shutdown request. The core
loop consumes it before visibility, pause or graphics checks and runs the normal
RetroArch `main_exit` path. This unloads the game, stops audio and releases browser
observers before Emscripten executes C++ global destructors and terminates workers.
Hosts wait for `Module.onExit` before removing the canvas; they must not directly
force-exit a running threaded core. Native regressions cover coalescing requests
and the core-loop boundary. No host route, game data or keyboard binding is part
of this private lifecycle ABI.

Browser resize observations publish positive dimensions and pixel ratio through
the platform atomics only. The graphics driver's window check applies changed
dimensions on the canvas-owning render thread. This avoids mutating layout in
ResizeObserver delivery or synchronously proxying canvas changes across threads;
unchanged dimensions never reset the drawing buffer. A native C regression runs
the patched upstream callbacks with explicit browser/render ownership.

Explicit local builds retain verified stage-one/core artifacts and Meson source
archives under this worktree's ignored `.cache/rpg-runtime-build/`. A stage-one
cache hit requires identical MKXP source, relevant stage recipe and toolchain bytes and a matching
artifact manifest; corrupt cached bytes fail closed. Later-stage failures do
not remove this cache. GNU archives are prefetched from the GNU origin with
the SHA-256 declared by the locked wrap file, avoiding mirror timeouts.
The pinned Meson version uses its standard
[package cache](https://mesonbuild.com/Wrap-dependency-system-manual.html)
for other source archives. Cache reuse never skips release verification.

The generated Ruby sandbox translation units use per-file release optimization,
not whole-program LTO; the MKXP core and other dependencies retain LTO. Core
compilation uses two jobs, wasm-ld one worker, and Binaryen two workers. This
avoids combining the large Ruby program into one memory-intensive LTO module,
without changing the threaded runtime ABI or save format. Core artifacts are
verified and cached before linking; a frontend-only change does not rebuild them.

Local frontend builds retain an optimized function-index symbol map under
`.cache/rpg-runtime-build/symbols/<wasm-sha256>.symbols`. Match the exact Wasm
digest before interpreting a browser's `wasm-function[index]` stack. The map
stays outside the closed candidate/release payload and does not change the
sandbox binding hash or checkpoint format.

Remote `.mkxpz` project and RTP archives are exposed through RetroArch's
WasmFS FetchFS backend. The Retrom build makes that backend fail closed: the
host must provide a bounded power-of-two chunk size, the remote endpoint must
advertise byte ranges, and every read must return an exact `206` response with
the expected `Content-Range` and byte length. It never falls back to a whole
archive download. The host remains responsible for creating the FetchFS
manifest and for passing content URLs; this fork does not know any Retrom API
or launch identifier.

The pinned FetchFS URL join is corrected at the base/path boundary: directory
paths already start with a slash, so appending another slash would request a
different URL. Escaped paths and query strings are preserved. The frontend
build clears only its ephemeral container's Emscripten system-library cache
after patching, ensuring a precompiled WasmFS cannot bypass this correction.

The pinned Emscripten FetchFS worker constructs its readiness flag, mutex and
condition variable before spawning its thread. The upstream declaration order
spawns first, allowing an eager worker to access unconstructed synchronization
and its ready signal to be overwritten, deadlocking before the first content
request. The exact SDK header is hash-checked before patching. A deterministic
native regression forces this early schedule, including against the full patched
SDK header during every frontend build. This preserves the existing startup
handshake, Range policy, owner-loop shutdown and checkpoint formats.

Metadata digests describe the uploaded bytes for cache diagnostics. A consumer
identifies the runtime by repository, tag, tag commit, asset filenames and
`mkxp-state`; observed digests are not release identity.
