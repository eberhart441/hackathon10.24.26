#pragma once
/* The 20-byte ESP-NOW broadcast sent by a responder tag (requirement 23.4). */

#include <stdint.h>

#define RS_TAG_MAGIC "RSTG"

typedef struct __attribute__((packed)) {
    char magic[4];     /* "RSTG", not NUL terminated */
    char tag_id[8];    /* commissioned tag ID, NUL padded */
    uint32_t seq;      /* increments per broadcast */
    uint32_t uptime_ms;
} rs_tag_packet_t;

_Static_assert(sizeof(rs_tag_packet_t) == 20, "tag packet must be 20 bytes");
