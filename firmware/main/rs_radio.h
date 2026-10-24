#pragma once

#include <stdbool.h>

#include "esp_err.h"
#include "rs_config.h"

/* Start WiFi in station mode on the configured channel at 20 MHz, power saving off,
 * ESP-NOW initialised. For a transmitter the MAC is set to cfg->own_mac so receivers
 * can recognise it. Does not enable CSI (the receiver does that). */
esp_err_t rs_radio_start(const rs_config_t *cfg);

/* Add the ESP-NOW broadcast peer. If `fixed_rate` is true, send at the lowest HT rate
 * so receivers get usable CSI; otherwise use the default rate. */
esp_err_t rs_radio_add_broadcast_peer(const rs_config_t *cfg, bool fixed_rate);

extern const unsigned char RS_BROADCAST_MAC[6];
