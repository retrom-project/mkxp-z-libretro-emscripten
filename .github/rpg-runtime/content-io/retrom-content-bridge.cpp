#include "retrom-content-bridge.h"
#include <emscripten.h>
#include <emscripten/proxying.h>
#include <emscripten/threading.h>
#include <atomic>
#include <cassert>
#include <cerrno>
#include <mutex>
#include <string>

namespace {
struct Task {
  std::string id;
  uint32_t low, high, length, timeout;
  uintptr_t destination;
  em_proxying_ctx* context = nullptr;
  int32_t result = -EIO;
  std::atomic<bool> abandoned{false};
};
pthread_once_t queueOnce = PTHREAD_ONCE_INIT;
em_proxying_queue* queue = nullptr;
void initializeQueue() {queue = em_proxying_queue_create();}
int errorNumber(int code) {
  switch (code) {
    case 1: return ENOENT;
    case 2: return EINVAL;
    case 9: return ETIMEDOUT;
    case 11: return ECANCELED;
    default: return EIO;
  }
}
}
extern "C" EMSCRIPTEN_KEEPALIVE void retrom_content_finish(Task* task, int32_t result, int code) {
  assert(emscripten_is_main_browser_thread());
  // A canceled target invalidates the SDK's stack-allocated context. Such an
  // orphan is retained until module teardown; never finish an invalid ctx.
  if (task->abandoned.load()) {return;}
  task->result = code ? -errorNumber(code) : result;
  emscripten_proxy_finish(task->context);
  // No task access after finish: the waiting thread can immediately delete it.
}
EM_JS(void, startRead, (Task* task, const char* fileId, uint32_t low, uint32_t high,
  uint32_t length, uint32_t timeout, uintptr_t destination), {
  const bridge = Module['retromContentBridge'];
  const expectedHash = '9601f63ba9d1bad095b42b32a3d6167166535be246a87f0efac7c5b125ed27bf';
  if (!bridge || bridge.abi !== 'content-io-v1' || bridge.contractSha256 !== expectedHash ||
      typeof bridge.readIntoById !== 'function' || typeof bridge.reportFailure !== 'function') {
    _retrom_content_finish(task, 0, 16); return;
  }
  const id = UTF8ToString(fileId), offset = high * 4294967296 + low;
  const controller = new AbortController(), bytes = new Uint8Array(length);
  const pending = Module['retromContentPending'] || (Module['retromContentPending'] = new Map());
  let settled = false;
  const finish = (count, code) => {
    if (settled) {return;}
    settled = true; clearTimeout(timer); pending.delete(task);
    controller.abort();
    if (code) {try {bridge.reportFailure(code);} catch (_) {}}
    _retrom_content_finish(task, count, code);
  };
  const timer = setTimeout(() => finish(0, 9), timeout);
  pending.set(task, () => finish(0, 11));
  Module['retromContentClose'] = () => {
    Module['retromContentClosed'] = true;
    for (const cancel of Array.from(pending.values())) {cancel();}
  };
  if (Module['retromContentClosed']) {finish(0, 11); return;}
  Promise.resolve().then(() => bridge.readIntoById(id, offset, bytes, controller.signal)).then(count => {
    if (settled) {return;}
    // WASM memory can grow while the Promise is pending. Reacquire HEAPU8.
    if (count !== length || destination > HEAPU8.length - length) {finish(0, 2); return;}
    HEAPU8.set(bytes, destination); finish(count, 0);
  }, error => {
    if (settled) {return;}
    const code = error && Number.isInteger(error.codeNumber) ? error.codeNumber :
      error && error.name === 'AbortError' ? 11 : 17;
    finish(0, code);
  });
});
static void dispatch(em_proxying_ctx* context, void* opaque) {
  assert(emscripten_is_main_browser_thread());
  auto* task = static_cast<Task*>(opaque);
  task->context = context;
  startRead(task, task->id.c_str(), task->low, task->high, task->length, task->timeout, task->destination);
}
extern "C" EMSCRIPTEN_KEEPALIVE int32_t retrom_content_read_bridge(const char* fileId, uint32_t low,
  uint32_t high, uint32_t length, uint32_t timeout, uintptr_t destination) {
  if (emscripten_is_main_browser_thread() || !fileId || length > 262144 || !timeout || timeout > 15000 || high > 2097151) {
    return -EINVAL;
  }
  pthread_once(&queueOnce, initializeQueue);
  if (!queue) {return -EIO;}
  auto* task = new Task;
  task->id = fileId; task->low = low; task->high = high; task->length = length;
  task->timeout = timeout; task->destination = destination;
  if (!emscripten_proxy_sync_with_ctx(queue, emscripten_main_runtime_thread_id(), dispatch, task)) {
    // With the pinned SDK this means enqueue failure or target death, not a
    // read error. The UI context may already have been canceled by the SDK.
    // Fail the native runtime; keep this small orphan alive until its module
    // is torn down so a delayed callback cannot dereference freed memory.
    task->abandoned.store(true);
    emscripten_force_exit(1);
    return -ECANCELED;
  }
  const int32_t result = task->result;
  delete task;
  return result;
}
