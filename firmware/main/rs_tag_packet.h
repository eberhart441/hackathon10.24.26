#pragma once
/* The 20-byte ESP-NOW broadcast sent by a responder tag. Layout from design.md
 * ("Tag_Packet wire layout"): magic 0, tag_id 4, seq 8, uptime_ms 12, reserved 16. */

#include <stdint.h>

#define RS_TAG_MAGIC "RSTG"

typedef struct __attribute__((packed)) {
    char magic[4];       /* "RSTG", not NUL terminated */
    char tag_id[4];      /* commissioned tag ID, NUL padded (so up to 4 characters) */
    uint32_t seq;        /* little endian; increments per broadcast */
    uint32_t uptime_ms;  /* little endian */
    uint8_t reserved[4]; /* zero, for future use */
} rs_tag_packet_t;

_Static_assert(sizeof(rs_tag_packet_t) == 20, "tag packet must be 20 bytes");
