#pragma once

#include <stdint.h>

#include "rs_config.h"

/* Start broadcasting this tag's ID ~cfg->pps times per second with random timing jitter. */
void rs_tag_start(const rs_config_t *cfg);

/* Broadcasts sent since the last call. */
uint32_t rs_tag_take_count(void);
