// Deterministic scheduler for the pinned SDK's actual ProxyWorker constructor.
#include <cassert>
#include <functional>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <unordered_set>

static std::unordered_set<const void*> liveMutexes, liveConditions;
struct CheckedMutex {
  CheckedMutex() { liveMutexes.insert(this); }
  ~CheckedMutex() { liveMutexes.erase(this); }
  void lock() {
    if (!liveMutexes.count(this)) {
      throw std::runtime_error("worker entered before its mutex was constructed");
    }
  }
  void unlock() {}
};
struct CheckedCondition {
  CheckedCondition() { liveConditions.insert(this); }
  ~CheckedCondition() { liveConditions.erase(this); }
  void notify_all() {
    if (!liveConditions.count(this)) {
      throw std::runtime_error("worker notified an unconstructed condition variable");
    }
  }
  template<class Lock, class Predicate> void wait(Lock&, Predicate ready) {
    if (!ready()) { throw std::runtime_error("ready notification overwritten: startup deadlock"); }
  }
};
struct ImmediateThread {
  template<class Function> explicit ImmediateThread(Function callback) { callback(); }
  int native_handle() const { return 0; }
  void join() {}
};
using em_proxying_queue = int;
namespace emscripten {
struct ProxyingQueue {
  struct ProxyingCtx {};
  em_proxying_queue* queue = nullptr;
  template<class Function> void proxySync(int, Function) {}
  template<class Function> void proxySyncWithCtx(int, Function) {}
};
}
extern "C" void _wasmfs_thread_utils_heartbeat(em_proxying_queue*) {}
static inline bool emscripten_is_main_browser_thread() { return false; }
static inline void emscripten_exit_with_live_runtime() {}
static inline void cancelThread(int) {}

// SDK_SOURCE

int main() {
  try {
    emscripten::ProxyWorker worker;
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
