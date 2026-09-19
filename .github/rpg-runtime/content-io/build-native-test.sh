#!/usr/bin/env bash
set -euo pipefail
source_root=${1:?source}
output=${2:?output}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/source/retroarch/frontend/drivers"
cp "$source_root/retroarch/frontend/drivers/platform_emscripten.c" "$work/source/retroarch/frontend/drivers/"
cp "$source_root/retroarch/Makefile.emscripten" "$work/source/retroarch/"
python3 "$source_root/.github/rpg-runtime/patch-remote-content.py" --source "$work/source" --emscripten-root "$(em-config EMSCRIPTEN_ROOT)"
emcc --clear-cache
recipe="$source_root/.github/rpg-runtime/content-io"
set -x
em++ -std=c++17 -O1 -g -pthread -sPTHREAD_POOL_SIZE=4 -sPROXY_TO_PTHREAD=1 -sWASMFS=1 \
  -sALLOW_MEMORY_GROWTH=1 -sINITIAL_MEMORY=33554432 -sEXIT_RUNTIME=0 -sASSERTIONS=1 \
  -sEXPORTED_FUNCTIONS=_main,_malloc,_free,_emscripten_proxy_execute_queue,_retrom_content_finish \
  -sEXPORTED_RUNTIME_METHODS=HEAPU8,PThread -sEXPORT_NAME=ContentNativeFixture -sMODULARIZE=1 \
  "$recipe/test-native.cpp" "$recipe/retrom-content-bridge.cpp" "$recipe/retrom-content-manifest.cpp" \
  -o "$output/content-native.js"
python3 "$recipe/native-test-receipt.py" "$source_root" "$output"
