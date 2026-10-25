/* Read-only browser status, shared with RetroArch's core thread. */
#include "runtime-status.h"
#include <stdint.h>

#ifdef __EMSCRIPTEN__
#include <emscripten/emscripten.h>
#else
#define EMSCRIPTEN_KEEPALIVE
#endif

static uint32_t presented_frames;
enum { STATE_RUNNING = 3, STATE_SUCCEEDED = 4, STATE_FAILED = -1 };
static int state_operation;
static int exit_requested;
static int game_result;

/* A Ruby exception can stop game rendering while RetroArch stays alive. */
void runtime_game_failed(void)
{
   __atomic_store_n(&game_result, -1, __ATOMIC_RELEASE);
}

EMSCRIPTEN_KEEPALIVE int runtime_get_game_result(void)
{
   return __atomic_load_n(&game_result, __ATOMIC_ACQUIRE);
}

/* The browser must not execute C++ destructors while the core/audio threads
 * still use their globals. Only publish intent here; the core loop owns exit. */
EMSCRIPTEN_KEEPALIVE void runtime_request_exit(void)
{
   __atomic_store_n(&exit_requested, 1, __ATOMIC_RELEASE);
}

bool runtime_take_exit_request(void)
{
   return __atomic_exchange_n(&exit_requested, 0, __ATOMIC_ACQ_REL) != 0;
}

EMSCRIPTEN_KEEPALIVE uint32_t runtime_get_frame_count(void)
{
   return __atomic_load_n(&presented_frames, __ATOMIC_ACQUIRE);
}

EMSCRIPTEN_KEEPALIVE int runtime_get_state_result(void)
{
   int state = __atomic_load_n(&state_operation, __ATOMIC_ACQUIRE);
   return state == STATE_SUCCEEDED ? 1 : state == STATE_FAILED ? -1 : 0;
}

void runtime_frame_presented(void)
{
   __atomic_fetch_add(&presented_frames, 1, __ATOMIC_RELEASE);
}

EMSCRIPTEN_KEEPALIVE int runtime_request_state(int operation)
{
   int previous;
   if (operation != RUNTIME_STATE_SAVE && operation != RUNTIME_STATE_RESTORE)
      return 0;
   previous = __atomic_load_n(&state_operation, __ATOMIC_ACQUIRE);
   do {
      if (previous != 0 && previous != STATE_SUCCEEDED && previous != STATE_FAILED)
         return 0;
   } while (!__atomic_compare_exchange_n(&state_operation, &previous, operation,
               false, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE));
   return 1;
}

int runtime_take_state_request(void)
{
   int requested = __atomic_load_n(&state_operation, __ATOMIC_ACQUIRE);
   if (requested != RUNTIME_STATE_SAVE && requested != RUNTIME_STATE_RESTORE)
      return 0;
   return __atomic_compare_exchange_n(&state_operation, &requested, STATE_RUNNING,
         false, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE) ? requested : 0;
}

void runtime_state_finished(bool success)
{
   __atomic_store_n(&state_operation, success ? STATE_SUCCEEDED : STATE_FAILED, __ATOMIC_RELEASE);
}
