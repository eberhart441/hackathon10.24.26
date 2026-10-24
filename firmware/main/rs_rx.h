#pragma once

#include <stdint.h>

#include "rs_config.h"

/* Start receiving: CSI from the paired transmitter only, plus responder-tag broadcasts. */
void rs_rx_start(const rs_config_t *cfg);

/* CSI packets accepted from the paired transmitter since the last call. */
uint32_t rs_rx_take_count(void);

/* Records dropped because the output queue was full (cumulative). */
uint32_t rs_rx_dropped(void);

/* Print one TAG line for each commissioned tag heard since the last call, then reset. */
void rs_rx_emit_tag_summaries(const rs_config_t *cfg);
