#pragma once
/* Optional relay: receivers send their data lines over the air to the master, which prints
 * them on its USB port, so only the master has to be plugged into the laptop.
 *
 * Off by default. Receiver: SET relay_to=<master mac>. Master: SET relays=<rx mac>,<rx mac>.
 * The lines are exactly the ones a cabled receiver prints (CSI, HB, TAG), batched into
 * ESP-NOW frames that start with "RSRL". The master prints only frames from the listed
 * receivers, and only whole lines. */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "rs_config.h"

#define RS_RELAY_MAGIC "RSRL"

/* Receiver: start relaying if cfg->relay_to is set. Call after rs_radio_start and before rs_rx_start. */
void rs_relay_init_sender(const rs_config_t *cfg);

/* Receiver data path for CSI, HB and TAG lines: goes to the serial port, or into the relay batch. */
void rs_data_write(const char *line, size_t len);

/* Lines dropped by the relay (frames that could not be queued or were not acknowledged). Cumulative. */
uint32_t rs_relay_dropped(void);

/* Master: if cfg lists relaying receivers, print their frames on the serial port. Call after rs_radio_start. */
void rs_relay_start_gateway(const rs_config_t *cfg);
