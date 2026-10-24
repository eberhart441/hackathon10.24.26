#pragma once
/* Per-board settings, stored in flash so they survive reboots and can be changed
 * over serial without reflashing (requirement 3). Setting names follow design.md:
 * node_id, room_id, rx_mode, paired_tx, peer, tags, pps, channel (plus role and tag_id). */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

#define RS_NAME_MAX 15  /* node_id / room_id */
#define RS_TAG_ID_MAX 4 /* tag_id: 4 bytes in the tag packet */
#define RS_TAGS_BUF 64
#define RS_MAX_TAGS 6

typedef enum {
    RS_ROLE_TX = 0,
    RS_ROLE_RX = 1,
    RS_ROLE_TAG = 2,
} rs_role_t;

typedef struct {
    char node_id[RS_NAME_MAX + 1];
    char room_id[RS_NAME_MAX + 1];
    rs_role_t role;
    uint8_t channel; /* 1, 6 or 11 */
    uint16_t pps;    /* tx: packets/s, tag: broadcasts/s */
    uint8_t peer[6];      /* tx: the paired receiver to unicast to (ff:ff:ff:ff:ff:ff = broadcast) */
    uint8_t paired_tx[6]; /* rx: the only transmitter this receiver listens to */
    char tag_id[RS_TAG_ID_MAX + 1]; /* tag: this tag's ID */
    char tags[RS_TAGS_BUF];         /* rx: commissioned tag IDs, comma separated */
} rs_config_t;

const char *rs_role_name(rs_role_t role);

void rs_config_defaults(rs_config_t *cfg);

/* Fills `cfg` from flash; anything missing keeps its default. Always leaves `cfg` valid. */
void rs_config_load(rs_config_t *cfg);

esp_err_t rs_config_save(const rs_config_t *cfg);
esp_err_t rs_config_erase(void);

/* Validate and apply one setting. On failure returns false and sets *err to a short reason. */
bool rs_config_set(rs_config_t *cfg, const char *key, const char *value, const char **err);
