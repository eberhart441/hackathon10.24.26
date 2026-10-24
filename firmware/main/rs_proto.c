#include "rs_proto.h"

#include <stdio.h>
#include <stdlib.h>

static size_t finish(size_t cap, int written)
{
    if (written < 0 || (size_t)written >= cap) {
        return 0;
    }
    return (size_t)written;
}

size_t rs_fmt_csi(char *buf, size_t cap, const char *node_id, const char *tx_mac, uint32_t seq, uint32_t ts_us,
                  int rssi_dbm, unsigned channel, const uint8_t *amps, unsigned n_sub)
{
    int n = snprintf(buf, cap, "CSI,%s,%s,%lu,%lu,%d,%u,%u", node_id, tx_mac, (unsigned long)seq,
                     (unsigned long)ts_us, rssi_dbm, channel, n_sub);
    if (n < 0 || (size_t)n >= cap) {
        return 0;
    }
    size_t used = (size_t)n;
    for (unsigned i = 0; i < n_sub; i++) {
        int w = snprintf(buf + used, cap - used, ",%u", (unsigned)amps[i]);
        if (w < 0 || (size_t)w >= cap - used) {
            return 0;
        }
        used += (size_t)w;
    }
    if (used + 2 > cap) {
        return 0;
    }
    buf[used++] = '\n';
    buf[used] = '\0';
    return used;
}

size_t rs_fmt_hb(char *buf, size_t cap, const char *node_id, const char *room_id, const char *paired_tx_mac,
                 const char *fw_version, uint32_t uptime_ms, unsigned measured_pps, uint32_t free_heap,
                 uint32_t csi_q_drops, const char *rx_mode)
{
    return finish(cap, snprintf(buf, cap, "HB,%s,%s,%s,%s,%lu,%u,%lu,%lu,%s\n", node_id, room_id, paired_tx_mac,
                                fw_version, (unsigned long)uptime_ms, measured_pps, (unsigned long)free_heap,
                                (unsigned long)csi_q_drops, rx_mode));
}

size_t rs_fmt_tag(char *buf, size_t cap, const char *node_id, const char *room_id, const char *tag_id,
                  unsigned packets_heard, int rssi_sum, int max_rssi)
{
    if (packets_heard == 0) {
        return 0;
    }
    /* mean in tenths of a dB, rounded to nearest (half away from zero) */
    long tenths_num = (long)rssi_sum * 10L;
    long tenths = (tenths_num >= 0 ? tenths_num + (long)packets_heard / 2 : tenths_num - (long)packets_heard / 2) /
                  (long)packets_heard;
    const char *sign = tenths < 0 ? "-" : "";
    long a = labs(tenths);
    return finish(cap, snprintf(buf, cap, "TAG,%s,%s,%s,%u,%s%ld.%ld,%d\n", node_id, room_id, tag_id, packets_heard,
                                sign, a / 10, a % 10, max_rssi));
}
