#include "rs_proto.h"

#include <stdio.h>
#include <stdlib.h>

static size_t finish(char *buf, size_t cap, int written)
{
    if (written < 0 || (size_t)written >= cap) {
        return 0;
    }
    return (size_t)written;
}

size_t rs_fmt_boot(char *buf, size_t cap, const char *node_id, const char *role, const char *room_id,
                   const char *fw_version, unsigned channel, const char *bandwidth)
{
    return finish(buf, cap,
                  snprintf(buf, cap, "BOOT,%s,%s,%s,%s,%u,%s\n", node_id, role, room_id, fw_version, channel, bandwidth));
}

size_t rs_fmt_hb(char *buf, size_t cap, const char *node_id, const char *role, const char *room_id,
                 uint32_t uptime_ms, unsigned pps, unsigned channel, uint32_t dropped)
{
    return finish(buf, cap,
                  snprintf(buf, cap, "HB,%s,%s,%s,%lu,%u,%u,%lu\n", node_id, role, room_id,
                           (unsigned long)uptime_ms, pps, channel, (unsigned long)dropped));
}

size_t rs_fmt_csi(char *buf, size_t cap, const char *node_id, const char *room_id, const char *tx_mac,
                  uint32_t seq, uint32_t t_us, int rssi, unsigned channel, const uint8_t amps[RS_AMP_COUNT])
{
    int n = snprintf(buf, cap, "CSI,%s,%s,%s,%lu,%lu,%d,%u,%d", node_id, room_id, tx_mac,
                     (unsigned long)seq, (unsigned long)t_us, rssi, channel, RS_AMP_COUNT);
    if (n < 0 || (size_t)n >= cap) {
        return 0;
    }
    size_t used = (size_t)n;
    for (int i = 0; i < RS_AMP_COUNT; i++) {
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

size_t rs_fmt_tag(char *buf, size_t cap, const char *node_id, const char *room_id, const char *tag_id,
                  unsigned packets_heard, int rssi_sum, int max_rssi)
{
    if (packets_heard == 0) {
        return 0;
    }
    /* mean in tenths of a dB, rounded to nearest (half away from zero) */
    long tenths_num = (long)rssi_sum * 10L;
    long tenths = (tenths_num >= 0 ? tenths_num + (long)packets_heard / 2 : tenths_num - (long)packets_heard / 2)
                  / (long)packets_heard;
    const char *sign = tenths < 0 ? "-" : "";
    long a = labs(tenths);
    return finish(buf, cap,
                  snprintf(buf, cap, "TAG,%s,%s,%s,%u,%s%ld.%ld,%d\n", node_id, room_id, tag_id, packets_heard,
                           sign, a / 10, a % 10, max_rssi));
}
