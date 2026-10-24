#include "rs_util.h"

#include <ctype.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

bool rs_valid_name(const char *s, size_t max_len)
{
    if (s == NULL) {
        return false;
    }
    size_t n = strlen(s);
    if (n == 0 || n > max_len) {
        return false;
    }
    for (size_t i = 0; i < n; i++) {
        char c = s[i];
        if (!(isalnum((unsigned char)c) || c == '_' || c == '-')) {
            return false;
        }
    }
    return true;
}

bool rs_mac_parse(const char *s, uint8_t out[6])
{
    if (s == NULL || strlen(s) != 17) {
        return false;
    }
    uint8_t tmp[6];
    for (int i = 0; i < 6; i++) {
        const char *p = s + i * 3;
        if (!isxdigit((unsigned char)p[0]) || !isxdigit((unsigned char)p[1])) {
            return false;
        }
        if (i < 5 && p[2] != ':') {
            return false;
        }
        char pair[3] = {p[0], p[1], 0};
        tmp[i] = (uint8_t)strtoul(pair, NULL, 16);
    }
    memcpy(out, tmp, 6);
    return true;
}

void rs_mac_format(const uint8_t mac[6], char out[18])
{
    snprintf(out, 18, "%02x:%02x:%02x:%02x:%02x:%02x", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

bool rs_mac_is_broadcast(const uint8_t mac[6])
{
    for (int i = 0; i < 6; i++) {
        if (mac[i] != 0xff) {
            return false;
        }
    }
    return true;
}

bool rs_mac_is_zero(const uint8_t mac[6])
{
    for (int i = 0; i < 6; i++) {
        if (mac[i] != 0) {
            return false;
        }
    }
    return true;
}

int rs_mac_list_parse(const char *s, uint8_t out[][6], int max)
{
    if (s == NULL) {
        return -1;
    }
    if (s[0] == '\0' || strcmp(s, "none") == 0) {
        return 0;
    }
    int count = 0;
    const char *p = s;
    for (;;) {
        const char *end = strchr(p, ',');
        size_t len = end ? (size_t)(end - p) : strlen(p);
        char item[18];
        if (len != 17 || count >= max) {
            return -1;
        }
        memcpy(item, p, 17);
        item[17] = '\0';
        if (!rs_mac_parse(item, out[count]) || (out[count][0] & 0x01) != 0) {
            return -1;
        }
        count++;
        if (end == NULL) {
            return count;
        }
        p = end + 1;
    }
}

uint8_t rs_amplitude(int8_t imag, int8_t real, float gain)
{
    float mag = sqrtf((float)(imag * imag + real * real)) * gain;
    if (mag < 0.0f) {
        return 0;
    }
    if (mag > 255.0f) {
        return 255;
    }
    return (uint8_t)(mag + 0.5f);
}

bool rs_list_contains(const char *list, const char *id)
{
    if (list == NULL || id == NULL || id[0] == '\0') {
        return false;
    }
    size_t id_len = strlen(id);
    const char *p = list;
    while (*p != '\0') {
        const char *end = strchr(p, ',');
        size_t len = end ? (size_t)(end - p) : strlen(p);
        if (len == id_len && strncmp(p, id, len) == 0) {
            return true;
        }
        if (end == NULL) {
            break;
        }
        p = end + 1;
    }
    return false;
}

bool rs_valid_tag_list(const char *list, size_t max_items)
{
    if (list == NULL) {
        return false;
    }
    if (list[0] == '\0') {
        return true;
    }
    size_t items = 0;
    const char *p = list;
    for (;;) {
        const char *end = strchr(p, ',');
        size_t len = end ? (size_t)(end - p) : strlen(p);
        char item[8];
        if (len == 0 || len > 4 || len >= sizeof(item)) {
            return false;
        }
        memcpy(item, p, len);
        item[len] = '\0';
        if (!rs_valid_name(item, 4)) {
            return false;
        }
        if (++items > max_items) {
            return false;
        }
        if (end == NULL) {
            return true;
        }
        p = end + 1;
    }
}
