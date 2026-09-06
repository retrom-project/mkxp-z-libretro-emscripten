#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
stage1_image=ubuntu@sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517
emscripten_image=emscripten/emsdk@sha256:92c97951b9a6835cb5da9592e9d95226f67e09ecd01a541d817a5b4801f235a4

build_stage1() {
  local work=${1:?work directory is required}
  local artifacts=${2:?artifact directory is required}
  local source_root="$work/source"
  local jobs
  export GIT_CONFIG_GLOBAL=/dev/null SOURCE_DATE_EPOCH=0 TZ=UTC

  jobs=$(nproc)
  if ((jobs > 4)); then
    jobs=4
  fi

  cp -a "$root/." "$source_root"
  curl --fail --location --retry 3 -o "$work/wasi.tar.gz" \
    https://github.com/WebAssembly/wasi-sdk/releases/download/wasi-sdk-30/wasi-sdk-30.0-x86_64-linux.tar.gz
  mkdir "$work/wasi"
  tar -xzf "$work/wasi.tar.gz" -C "$work/wasi" --strip-components=1
  curl --fail --location --retry 3 -o "$work/binaryen.tar.gz" \
    https://github.com/WebAssembly/binaryen/releases/download/version_126/binaryen-version_126-x86_64-linux.tar.gz
  mkdir "$work/binaryen"
  tar -xzf "$work/binaryen.tar.gz" -C "$work/binaryen" --strip-components=1

  git -C "$source_root/mkxp-z" apply \
    "$source_root/.github/rpg-runtime/mkxp-deterministic-bindings.patch"
  python3 "$source_root/.github/rpg-runtime/patch-runtime.py" --source "$source_root"
  make -C "$source_root/mkxp-z/libretro" -j "$jobs" \
    PWD="$source_root/mkxp-z/libretro" \
    WASI_SDK="$work/wasi" \
    WASM_OPT="$work/binaryen/bin/wasm-opt"
  mkdir -p "$artifacts/stage1"
  cp -a "$source_root/mkxp-z/libretro/build/libretro-stage1/." \
    "$artifacts/stage1/"
}

build_core() {
  local work=${1:?work directory is required}
  local artifacts=${2:?artifact directory is required}
  local source_root="$work/source"
  export GIT_CONFIG_GLOBAL=/dev/null SOURCE_DATE_EPOCH=0 TZ=UTC

  cp -a "$root/." "$source_root"
  git -C "$source_root/mkxp-z" apply \
    "$source_root/.github/rpg-runtime/mkxp-deterministic-bindings.patch"
  python3 "$source_root/.github/rpg-runtime/patch-runtime.py" \
    --source "$source_root"
  python3 "$source_root/.github/rpg-runtime/patch-build-memory.py" \
    --source "$source_root"
  mkdir -p "$source_root/mkxp-z/libretro/build/libretro-stage1"
  cp -a "$artifacts/stage1/." \
    "$source_root/mkxp-z/libretro/build/libretro-stage1/"

  cat > "$work/cross.ini" <<EOF
[binaries]
c = 'emcc'
cpp = 'em++'
ar = 'emar'
cmake = 'cmake'
[host_machine]
system = 'emscripten'
cpu_family = 'wasm32'
cpu = 'wasm32'
endian = 'little'
[properties]
cmake_toolchain_file = '$(em-config EMSCRIPTEN_ROOT)/cmake/Modules/Platform/Emscripten.cmake'
EOF
  meson setup "$source_root/mkxp-z/build" "$source_root/mkxp-z" \
    --cross-file "$work/cross.ini" \
    --buildtype release \
    -Db_lto=true \
    -Dlibretro=true \
    -Dlibretro_save_states=true \
    -Demscripten_threaded=true
  ninja -j 2 -C "$source_root/mkxp-z/build"
  install -m 0644 "$source_root/mkxp-z/build/mkxp-z_libretro.a" \
    "$artifacts/mkxp-z_libretro.a"
}

build_frontend() {
  local work=${1:?work directory is required}
  local artifacts=${2:?artifact directory is required}
  local output=${3:?output directory is required}
  local source_root="$work/source"
  local commit
  export GIT_CONFIG_GLOBAL=/dev/null SOURCE_DATE_EPOCH=0 TZ=UTC

  cp -a "$root/." "$source_root"
  python3 "$source_root/.github/rpg-runtime/patch-runtime-status.py" \
    --source "$source_root"
  python3 "$source_root/.github/rpg-runtime/patch-canvas-resize.py" \
    --source "$source_root"
  python3 "$source_root/.github/rpg-runtime/patch-remote-content.py" \
    --source "$source_root" \
    --emscripten-root "$(em-config EMSCRIPTEN_ROOT)"
  python3 "$source_root/.github/rpg-runtime/test_thread_startup.py" \
    --sdk-header "$(em-config EMSCRIPTEN_ROOT)/system/lib/wasmfs/thread_utils.h"
  # FetchFS changes a system-library C++ source. Never reuse the image's
  # precompiled WasmFS in place of the patched source (container-local only).
  emcc --clear-cache
  install -m 0644 "$artifacts/mkxp-z_libretro.a" \
    "$source_root/retroarch/libretro_emscripten.a"
  emmake make -C "$source_root/retroarch" -f Makefile.emscripten \
    LIBRETRO=mkxp-z \
    HAVE_THREADS=1 \
    PROXY_TO_PTHREAD=1 \
    HAVE_AUDIOWORKLET=1 \
    HAVE_RWEBAUDIO=0 \
    HAVE_AL=0 \
    HAVE_WASMFS=1 \
    HAVE_EXTRA_WASMFS=1
  install -m 0644 "$source_root/retroarch/mkxp-z_libretro.js" \
    "$output/mkxp-z_libretro.js"
  install -m 0644 "$source_root/retroarch/mkxp-z_libretro.wasm" \
    "$output/mkxp-z_libretro.wasm"
  # Keep diagnostics outside the closed release/candidate asset directory.
  install -m 0644 "$source_root/retroarch/mkxp-z_libretro.js.symbols" \
    "$artifacts/mkxp-z_libretro.symbols"
  commit=$(git -C "$source_root" rev-parse HEAD)
  python3 "$source_root/.github/rpg-runtime/verify-release.py" \
    --source "$root" \
    --output "$output" \
    --repository https://github.com/retrom-project/mkxp-z-libretro-emscripten \
    --tag retrom-core-f2efc98-r999999 \
    --commit "$commit"
}

case ${1:-} in
  --stage1-in-container)
    build_stage1 \
      "${2:?work directory is required}" \
      "${3:?artifact directory is required}"
    exit
    ;;
  --core-in-container)
    build_core \
      "${2:?work directory is required}" \
      "${3:?artifact directory is required}"
    exit
    ;;
  --frontend-in-container)
    build_frontend \
      "${2:?work directory is required}" \
      "${3:?artifact directory is required}" \
      "${4:?output directory is required}"
    exit
    ;;
esac

output=${1:?absolute empty output directory is required}
work=$(mktemp -d "${TMPDIR:-/tmp}/retrom-mkxp-candidate.XXXXXX")
trap 'rm -rf "$work"' EXIT INT TERM
python3 "$root/.github/rpg-runtime/source-snapshot.py" --source "$root" --output "$work/input"
source_input="$work/input"
cache_root="$root/.cache/rpg-runtime-build"
mkdir -p "$cache_root/meson"
python3 "$root/.github/rpg-runtime/build-cache.py" wrap "$root/mkxp-z/subprojects/libiconv.wrap" "$cache_root/meson"
python3 "$root/.github/rpg-runtime/build-cache.py" wrap "$root/mkxp-z/subprojects/libidn.wrap" "$cache_root/meson"
stage1_key=$(python3 "$root/.github/rpg-runtime/build-cache.py" key "$source_input")
mkdir -p \
  "$work/artifacts" \
  "$work/stage1/user-cache" "$work/stage1/user-config" \
  "$work/core/user-cache" "$work/core/user-config" \
  "$work/frontend/user-cache" "$work/frontend/user-config"
build_uid=$(id -u)
build_gid=$(id -g)

stage1_cached=$(python3 "$root/.github/rpg-runtime/build-cache.py" restore "$cache_root/stage1/$stage1_key" "$work/artifacts/stage1")
if [[ "$stage1_cached" != hit ]]; then
docker run --rm --platform linux/amd64 --hostname rpg-runtime-mkxp-stage1 \
  --volume "$source_input:/input:ro" \
  --volume "$work:/work" \
  --workdir /work \
  "$stage1_image" \
  bash -euo pipefail -c '
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends automake build-essential ca-certificates curl git libtool python3 ruby universal-ctags util-linux zip
    exec setpriv --reuid="$1" --regid="$2" --clear-groups \
      env XDG_CACHE_HOME=/work/stage1/user-cache XDG_CONFIG_HOME=/work/stage1/user-config \
      /input/.github/rpg-runtime/build-web.sh --stage1-in-container /work/stage1 /work/artifacts
  ' bash "$build_uid" "$build_gid"

python3 "$root/.github/rpg-runtime/build-cache.py" store "$work/artifacts/stage1" "$cache_root/stage1/$stage1_key"
fi
find "$work/stage1" -mindepth 1 -delete

core_key=$(python3 "$root/.github/rpg-runtime/build-cache.py" core-key "$source_input")
core_cached=$(python3 "$root/.github/rpg-runtime/build-cache.py" restore "$cache_root/core/$core_key" "$work/core-cache")
if [[ "$core_cached" == hit ]]; then
  install -m 0644 "$work/core-cache/mkxp-z_libretro.a" "$work/artifacts/mkxp-z_libretro.a"
else
docker run --rm --platform linux/amd64 --hostname rpg-runtime-mkxp-core \
  --volume "$source_input:/input:ro" \
  --volume "$cache_root/meson:/cache" \
  --volume "$work:/work" \
  --volume "$output:/output" \
  --workdir /work \
  "$emscripten_image" \
  bash -euo pipefail -c '
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends ninja-build util-linux
    python3 -m pip install --no-cache-dir cmake==3.28.3 meson==1.3.2
    exec setpriv --reuid="$1" --regid="$2" --clear-groups \
      env MESON_PACKAGE_CACHE_DIR=/cache XDG_CACHE_HOME=/work/core/user-cache XDG_CONFIG_HOME=/work/core/user-config \
      /input/.github/rpg-runtime/build-web.sh --core-in-container /work/core /work/artifacts
  ' bash "$build_uid" "$build_gid"
mkdir -p "$work/core-cache"
install -m 0644 "$work/artifacts/mkxp-z_libretro.a" "$work/core-cache/mkxp-z_libretro.a"
python3 "$root/.github/rpg-runtime/build-cache.py" store "$work/core-cache" "$cache_root/core/$core_key"
fi
find "$work/core" -mindepth 1 -delete

docker run --rm --platform linux/amd64 --hostname rpg-runtime-mkxp-frontend \
  --volume "$source_input:/input:ro" \
  --volume "$work:/work" \
  --volume "$output:/output" \
  --workdir /work \
  "$emscripten_image" \
  bash -euo pipefail -c '
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends util-linux
    # The image owns its SDK as UID 1000; CI and PFB may use another UID.
    # Only the disposable container SDK is writable, never the input mount.
    chown -R "$1:$2" "$(em-config EMSCRIPTEN_ROOT)"
    exec setpriv --reuid="$1" --regid="$2" --clear-groups \
      env XDG_CACHE_HOME=/work/frontend/user-cache XDG_CONFIG_HOME=/work/frontend/user-config \
      /input/.github/rpg-runtime/build-web.sh --frontend-in-container /work/frontend /work/artifacts /output
  ' bash "$build_uid" "$build_gid"

wasm_sha=$(sha256sum "$output/mkxp-z_libretro.wasm")
wasm_sha=${wasm_sha%% *}
mkdir -p "$cache_root/symbols"
install -m 0644 "$work/artifacts/mkxp-z_libretro.symbols" \
  "$cache_root/symbols/$wasm_sha.symbols"
