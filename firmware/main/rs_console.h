#pragma once

#include "rs_config.h"

/* Start the serial command listener (PING, CFG GET/SET/RESET, REBOOT).
 * `live` is the config in use; `pending` is edited by CFG SET and saved to flash. */
void rs_console_start(const rs_config_t *live, rs_config_t *pending);
