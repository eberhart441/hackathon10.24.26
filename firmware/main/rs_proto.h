#pragma once
/* Formatting of serial protocol records. See firmware/docs/serial-protocol.md (the contract).
 * Every function writes a complete line INCLUDING the trailing '\n' into `buf`
 * and returns its length, or 0 if `cap` is too small. */

#include <stddef.h>
#include <stdint.h>

#include "rs_util.h"

#define RS_LINE_MAX 512 /* big enough for the longest CSI record (about 340 bytes) */

size_t rs_fmt_boot(char *buf, size_t cap, const char *node_id, const char *role, const char *room_id,
                   const char *fw_version, unsigned channel, const char *bandwidth);

size_t rs_fmt_hb(char *buf, size_t cap, const char *node_id, const char *role, const char *room_id,
                 uint32_t uptime_ms, unsigned pps, unsigned channel, uint32_t dropped);

size_t rs_fmt_csi(char *buf, size_t cap, const char *node_id, const char *room_id, const char *tx_mac,
                  uint32_t seq, uint32_t t_us, int rssi, unsigned channel, const uint8_t amps[RS_AMP_COUNT]);

/* mean_rssi is printed with one decimal from the integer sum, without floating point. */
size_t rs_fmt_tag(char *buf, size_t cap, const char *node_id, const char *room_id, const char *tag_id,
                  unsigned packets_heard, int rssi_sum, int max_rssi);
