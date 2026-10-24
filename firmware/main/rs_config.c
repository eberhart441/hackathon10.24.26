#include "rs_config.h"

#include <stdlib.h>
#include <string.h>

#include "nvs.h"
#include "sdkconfig.h"

#include "rs_util.h"

#define NVS_NAMESPACE "roomsense"
#define NVS_KEY "cfg"
#define CFG_MAGIC 0x52534332u /* "RSC2": bump when the struct layout changes */

typedef struct {
    uint32_t magic;
    rs_config_t cfg;
} stored_t;

const char *rs_role_name(rs_role_t role)
{
    switch (role) {
    case RS_ROLE_TX:
        return "tx";
    case RS_ROLE_RX:
        return "rx";
    default:
        return "tag";
    }
}

static uint16_t default_pps(rs_role_t role)
{
    return (role == RS_ROLE_TAG) ? (uint16_t)CONFIG_RS_DEFAULT_TAG_PPS : (uint16_t)CONFIG_RS_DEFAULT_TX_PPS;
}

void rs_config_defaults(rs_config_t *cfg)
{
    memset(cfg, 0, sizeof(*cfg));
    strlcpy(cfg->node_id, CONFIG_RS_DEFAULT_NODE_ID, sizeof(cfg->node_id));
    strlcpy(cfg->room_id, CONFIG_RS_DEFAULT_ROOM_ID, sizeof(cfg->room_id));
#if defined(CONFIG_RS_DEFAULT_ROLE_TX)
    cfg->role = RS_ROLE_TX;
#elif defined(CONFIG_RS_DEFAULT_ROLE_TAG)
    cfg->role = RS_ROLE_TAG;
#else
    cfg->role = RS_ROLE_RX;
#endif
    cfg->channel = (uint8_t)CONFIG_RS_DEFAULT_CHANNEL;
    cfg->pps = default_pps(cfg->role);
    memset(cfg->peer, 0xff, 6); /* broadcast until a receiver is paired */
    memset(cfg->paired_tx, 0, 6); /* nothing paired yet: a receiver accepts no CSI until this is set */
    strlcpy(cfg->tag_id, "E1", sizeof(cfg->tag_id));
    cfg->tags[0] = '\0';
}

static bool channel_ok(int ch)
{
    return ch == 1 || ch == 6 || ch == 11;
}

/* Reject anything a corrupted flash blob could contain. */
static bool config_valid(const rs_config_t *c)
{
    return rs_valid_name(c->node_id, RS_NAME_MAX) && rs_valid_name(c->room_id, RS_NAME_MAX) &&
           (c->role == RS_ROLE_TX || c->role == RS_ROLE_RX || c->role == RS_ROLE_TAG) && channel_ok(c->channel) &&
           c->pps >= 1 && c->pps <= 200 && rs_valid_name(c->tag_id, RS_TAG_ID_MAX) &&
           memchr(c->tags, '\0', sizeof(c->tags)) != NULL && rs_valid_tag_list(c->tags, RS_MAX_TAGS) &&
           ((c->peer[0] & 0x01) == 0 || rs_mac_is_broadcast(c->peer)) && (c->paired_tx[0] & 0x01) == 0;
}

void rs_config_load(rs_config_t *cfg)
{
    rs_config_defaults(cfg);
    nvs_handle_t h;
    if (nvs_open(NVS_NAMESPACE, NVS_READONLY, &h) != ESP_OK) {
        return;
    }
    stored_t s;
    size_t len = sizeof(s);
    if (nvs_get_blob(h, NVS_KEY, &s, &len) == ESP_OK && len == sizeof(s) && s.magic == CFG_MAGIC &&
        config_valid(&s.cfg)) {
        *cfg = s.cfg;
    }
    nvs_close(h);
}

esp_err_t rs_config_save(const rs_config_t *cfg)
{
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h);
    if (err != ESP_OK) {
        return err;
    }
    stored_t s = {.magic = CFG_MAGIC, .cfg = *cfg};
    err = nvs_set_blob(h, NVS_KEY, &s, sizeof(s));
    if (err == ESP_OK) {
        err = nvs_commit(h);
    }
    nvs_close(h);
    return err;
}

esp_err_t rs_config_erase(void)
{
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h);
    if (err != ESP_OK) {
        return err;
    }
    err = nvs_erase_all(h);
    if (err == ESP_OK) {
        err = nvs_commit(h);
    }
    nvs_close(h);
    return err;
}

static bool parse_int_range(const char *value, long low, long high, long *out)
{
    char *end;
    long v = strtol(value, &end, 10);
    if (*value == '\0' || *end != '\0' || v < low || v > high) {
        return false;
    }
    *out = v;
    return true;
}

bool rs_config_set(rs_config_t *cfg, const char *key, const char *value, const char **err)
{
    const char *dummy;
    if (err == NULL) {
        err = &dummy;
    }
    if (key == NULL || value == NULL) {
        *err = "missing_value";
        return false;
    }

    if (strcmp(key, "node_id") == 0) {
        if (!rs_valid_name(value, RS_NAME_MAX)) {
            *err = "bad_node_id";
            return false;
        }
        strlcpy(cfg->node_id, value, sizeof(cfg->node_id));
    } else if (strcmp(key, "room_id") == 0) {
        if (!rs_valid_name(value, RS_NAME_MAX)) {
            *err = "bad_room_id";
            return false;
        }
        strlcpy(cfg->room_id, value, sizeof(cfg->room_id));
    } else if (strcmp(key, "role") == 0) {
        rs_role_t role;
        if (strcmp(value, "tx") == 0) {
            role = RS_ROLE_TX;
        } else if (strcmp(value, "rx") == 0) {
            role = RS_ROLE_RX;
        } else if (strcmp(value, "tag") == 0) {
            role = RS_ROLE_TAG;
        } else {
            *err = "bad_role";
            return false;
        }
        if (role != cfg->role) {
            /* pps means different things per role, so changing role restores that role's default rate. */
            cfg->pps = default_pps(role);
        }
        cfg->role = role;
    } else if (strcmp(key, "channel") == 0) {
        long ch;
        if (!parse_int_range(value, 1, 13, &ch) || !channel_ok((int)ch)) {
            *err = "bad_channel";
            return false;
        }
        cfg->channel = (uint8_t)ch;
    } else if (strcmp(key, "pps") == 0) {
        long v;
        if (!parse_int_range(value, 1, 200, &v)) {
            *err = "bad_pps";
            return false;
        }
        cfg->pps = (uint16_t)v;
    } else if (strcmp(key, "peer") == 0) {
        uint8_t mac[6];
        if (!rs_mac_parse(value, mac) || ((mac[0] & 0x01) != 0 && !rs_mac_is_broadcast(mac))) {
            *err = "bad_mac";
            return false;
        }
        memcpy(cfg->peer, mac, 6);
    } else if (strcmp(key, "paired_tx") == 0) {
        uint8_t mac[6];
        if (!rs_mac_parse(value, mac) || (mac[0] & 0x01) != 0) {
            *err = "bad_mac";
            return false;
        }
        memcpy(cfg->paired_tx, mac, 6);
    } else if (strcmp(key, "tag_id") == 0) {
        if (!rs_valid_name(value, RS_TAG_ID_MAX)) {
            *err = "bad_tag_id";
            return false;
        }
        strlcpy(cfg->tag_id, value, sizeof(cfg->tag_id));
    } else if (strcmp(key, "tags") == 0) {
        if (strlen(value) >= sizeof(cfg->tags) || !rs_valid_tag_list(value, RS_MAX_TAGS)) {
            *err = "bad_tags";
            return false;
        }
        strlcpy(cfg->tags, value, sizeof(cfg->tags));
    } else if (strcmp(key, "rx_mode") == 0) {
        /* HUB_Mode is the only mode implemented. EDGE and TRAINING need the on-device
         * feature pipeline, which is not built yet. */
        if (strcmp(value, "HUB") != 0) {
            *err = "only_HUB_implemented";
            return false;
        }
    } else if (strcmp(key, "peers") == 0) {
        *err = "not_implemented"; /* Commissioned_RX list is only used by EDGE_Mode */
        return false;
    } else {
        *err = "unknown_key";
        return false;
    }
    return true;
}
