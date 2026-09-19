#!/usr/bin/env python3
"""Replace locked FetchFS transport with Content I/O capability calls, retaining WasmFS."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Callable


EMSCRIPTEN_FETCHFS_4_0_8_SHA256 = (
    "1065a11fb336e75b9e0164ca7058bf9d417da0d7463b40a0c8e67a770088678e"
)
EMSCRIPTEN_FETCH_BACKEND_4_0_8_SHA256 = (
    "1ff8036c23e9defca0b4987262fcacf6c388c7405d63e3946858eb56c8fe1f33"
)
EMSCRIPTEN_THREAD_UTILS_4_0_8_SHA256 = (
    "fbe0af47479f48fe2d98ced5f6b3c618256be1332aa0b420f0567980fbf60e96"
)

OLD_WORKER_MEMBERS = """  ProxyingQueue queue;
  std::thread thread;

  // Used to notify the calling thread once the worker has been started.
  bool started = false;
  std::mutex mutex;
  std::condition_variable cond;"""
NEW_WORKER_MEMBERS = """  ProxyingQueue queue;

  // Construct all worker-visible state before spawning the worker. C++ uses
  // member declaration order, regardless of the constructor initializer list.
  bool started = false;
  std::mutex mutex;
  std::condition_variable cond;
  std::thread thread;"""

def replace_exact(source: str, old: str, new: str, code: str) -> str:
    if source.count(old) != 1 or (new and new in source):
        raise ValueError(code)
    return source.replace(old, new)


def patch_retroarch(source: str) -> str:
    start = source.index('   if (fetch_manifest || fetch_base_dir)')
    end = source.index('\n}\n#endif /* HAVE_EXTRA_WASMFS */', start)
    if hashlib.sha256(source[start:end].encode()).hexdigest() != "f88cfb9f666dcd715b055d0bf1f9e3943012cf2b923f12b8fcb5f5c4d4a1860e":
        raise ValueError("RPG_RUNTIME_CONTENT_MANIFEST_SOURCE_INVALID")
    source = source[:start] + """   if (fetch_manifest || fetch_base_dir)
   {
      if (!(fetch_manifest && fetch_base_dir) ||
          retrom_content_mount_manifest(fetch_manifest, fetch_base_dir) != 0)
      {
         printf("[ContentIO] RETROM_CONTENT_IO_V1 manifest invalid\\n");
         abort();
      }
   }""" + source[end:]
    return replace_exact(source, '#include <emscripten/wasmfs.h>',
        '#include <emscripten/wasmfs.h>\n#include "retrom-content-bridge.h"',
        'RPG_RUNTIME_CONTENT_MANIFEST_INCLUDE_INVALID')


def patch_emscripten(source: str) -> str:
    if hashlib.sha256(source.encode()).hexdigest() != EMSCRIPTEN_FETCHFS_4_0_8_SHA256:
        raise ValueError("RPG_RUNTIME_EMSCRIPTEN_FETCHFS_SOURCE_INVALID")
    return (Path(__file__).parent / "content-io/libwasmfs_content.js").read_text()


def patch_fetch_backend_cpp(source: str) -> str:
    source = replace_exact(source, '  return baseUrl + "/" + filePath;',
        "  return filePath.front() == '/' ? filePath.substr(1) : filePath;",
        'RPG_RUNTIME_CONTENT_FILE_ID_INVALID')
    source = replace_exact(source, '  const std::string& getPath() const { return filePath; }',
        """  int open(oflags_t flags) override {
    return (flags & (O_WRONLY | O_RDWR | O_TRUNC | O_APPEND)) ? -EROFS : 0;
  }
  ssize_t write(const uint8_t*, size_t, off_t) override { return -EROFS; }
  int setSize(off_t) override { return -EROFS; }
  const std::string& getPath() const { return filePath; }""",
        'RPG_RUNTIME_CONTENT_READ_ONLY_INVALID')
    return source


def patch_thread_utils(source: str) -> str:
    # An eager worker used the mutex/condition before construction and its
    # started=true could be overwritten by the parent's later initializer.
    # Initialize its synchronization first; keep the existing handshake.
    return replace_exact(
        source,
        OLD_WORKER_MEMBERS,
        NEW_WORKER_MEMBERS,
        "RPG_RUNTIME_FETCHFS_THREAD_INITIALIZATION_INVALID",
    )


def patch_makefile(source: str) -> str:
    extra = '$(OBJDIR)/frontend/drivers/retrom-content-bridge.o $(OBJDIR)/frontend/drivers/retrom-content-manifest.o'
    source = replace_exact(source, 'RARCH_OBJ := $(addprefix $(OBJDIR)/,$(OBJ))',
        'RARCH_OBJ := $(addprefix $(OBJDIR)/,$(OBJ)) ' + extra,
        'RPG_RUNTIME_CONTENT_BUILD_INVALID')
    source = replace_exact(source, '   CFLAGS += -pthread -s SHARED_MEMORY',
        '   CFLAGS += -pthread -s SHARED_MEMORY\n   CXXFLAGS += -pthread -s SHARED_MEMORY',
        'RPG_RUNTIME_CONTENT_BUILD_THREADS_INVALID')
    return source + '\n' + extra + ': CXXFLAGS += -std=c++17 -O3\n'


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--emscripten-root", type=Path, required=True)
    args = parser.parse_args()
    sources = [
        ("src/lib/libwasmfs_fetch.js", EMSCRIPTEN_FETCHFS_4_0_8_SHA256, patch_emscripten),
        ("system/lib/wasmfs/backends/fetch_backend.cpp", EMSCRIPTEN_FETCH_BACKEND_4_0_8_SHA256, patch_fetch_backend_cpp),
        ("system/lib/wasmfs/thread_utils.h", EMSCRIPTEN_THREAD_UTILS_4_0_8_SHA256, patch_thread_utils),
    ]
    # Verify every anchor before any mutation; reject drift and reapplication.
    outputs = []
    for name, digest, patcher in sources:
        path = args.emscripten_root / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise SystemExit("RPG_RUNTIME_CONTENT_SDK_SOURCE_INVALID:" + name)
        outputs.append((path, patcher(path.read_text())))
    platform = args.source / "retroarch/frontend/drivers/platform_emscripten.c"
    outputs.append((platform, patch_retroarch(platform.read_text())))
    for path, value in outputs:
        path.write_text(value)
    recipe = Path(__file__).parent / "content-io"
    for name in ("retrom-content-bridge.h", "retrom-content-bridge.cpp", "retrom-content-manifest.cpp"):
        (args.source / "retroarch/frontend/drivers" / name).write_bytes((recipe / name).read_bytes())
    makefile = args.source / "retroarch/Makefile.emscripten"
    makefile.write_text(patch_makefile(makefile.read_text()))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
