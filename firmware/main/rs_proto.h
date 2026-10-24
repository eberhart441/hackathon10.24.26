#pragma once
/* Formatting of serial protocol records, exactly as defined in
 * .kiro/specs/roomsense-occupancy-tool/design.md ("Serial line formats") and summarised in
 * firmware/docs/serial-protocol.md. Every function writes a complete line INCLUDING the trailing
 * '\n' into `buf` and returns its length, or 0 if `cap` is too small. */

#include <stddef.h>
#include <stdint.h>

#include "rs_util.h"

#define RS_LINE_MAX 512 /* big enough for the longest CSI record (about 330 bytes) */

/* CSI,<node_id>,<tx_mac>,<seq>,<ts_us>,<rssi_dbm>,<channel>,<n_sub>,<amp_0>,...,<amp_n-1> */
size_t rs_fmt_csi(char *buf, size_t cap, const char *node_id, const char *tx_mac, uint32_t seq, uint32_t ts_us,
                  int rssi_dbm, unsigned channel, const uint8_t *amps, unsigned n_sub);

/* HB,<node_id>,<room_id>,<paired_tx_mac>,<fw_version>,<uptime_ms>,<measured_pps>,<free_heap>,<csi_q_drops>,<rx_mode>
 * Sent by receivers only. */
size_t rs_fmt_hb(char *buf, size_t cap, const char *node_id, const char *room_id, const char *paired_tx_mac,
                 const char *fw_version, uint32_t uptime_ms, unsigned measured_pps, uint32_t free_heap,
                 uint32_t csi_q_drops, const char *rx_mode);

/* TAG,<node_id>,<room_id>,<tag_id>,<packets_heard>,<mean_rssi>,<max_rssi>
 * The mean is printed from the integer sum with one decimal, without floating point. */
size_t rs_fmt_tag(char *buf, size_t cap, const char *node_id, const char *room_id, const char *tag_id,
                  unsigned packets_heard, int rssi_sum, int max_rssi);
