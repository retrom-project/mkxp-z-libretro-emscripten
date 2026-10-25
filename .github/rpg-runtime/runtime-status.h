/* Thread-safe browser lifecycle observations; no game or host-specific state. */
#ifndef MKXP_WEB_RUNTIME_STATUS_H
#define MKXP_WEB_RUNTIME_STATUS_H

#include <stdbool.h>

void runtime_frame_presented(void);
void runtime_game_failed(void);
enum { RUNTIME_STATE_SAVE = 1, RUNTIME_STATE_RESTORE = 2 };
int runtime_take_state_request(void);
void runtime_state_finished(bool success);
bool runtime_take_exit_request(void);

#endif
