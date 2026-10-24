#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"
#include "esp_wifi_types.h"
#include "rs_config.h"

extern const uint8_t RS_BROADCAST_MAC[6];

/* Start WiFi in station mode on the configured channel at 20 MHz, power saving off,
 * ESP-NOW initialised. Does not enable CSI (the receiver does that). The board keeps its
 * factory MAC address, which the paired receiver uses to recognise a transmitter. */
esp_err_t rs_radio_start(const rs_config_t *cfg);

/* Add an ESP-NOW peer (a unicast receiver, or the broadcast address). If `fixed_rate` is true,
 * send to it at the given HT20 rate; the transmitter uses MCS0 so the receiver gets usable OFDM
 * CSI (ESP-NOW's default rate does not produce CSI). */
esp_err_t rs_radio_add_peer(const uint8_t mac[6], uint8_t channel, bool fixed_rate, wifi_phy_rate_t rate);
