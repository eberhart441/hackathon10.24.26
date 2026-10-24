#pragma once

#include <stdint.h>

#include "rs_config.h"

/* Start broadcasting a 32-bit packet counter at cfg->pps packets per second. */
void rs_tx_start(const rs_config_t *cfg);
