#include "rs_rx.h"

#include <string.h>

#include "esp_log.h"
#include "esp_now.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "sdkconfig.h"

#include "rs_out.h"
#include "rs_proto.h"
#include "rs_radio.h"
#include "rs_tag_packet.h"
#include "rs_util.h"

#if CONFIG_IDF_TARGET_ESP32S3 || CONFIG_IDF_TARGET_ESP32C3 || CONFIG_IDF_TARGET_ESP32C5 || \
    CONFIG_IDF_TARGET_ESP32C6 || CONFIG_IDF_TARGET_ESP32C61
#define RS_GAIN_CONTROL 1
#include "esp_csi_gain_ctrl.h"
#else
#define RS_GAIN_CONTROL 0
#endif

static const char *TAG = "rs_rx";

/* Where the transmitter's 32-bit counter sits inside the received frame payload.
 * Taken from the esp-csi csi_recv example (ESP-NOW frame header precedes the user data). */
#define RS_SEQ_OFFSET 15

/* A packet as copied out of the WiFi callback. Heavy work (square roots, text) happens later. */
typedef struct {
    uint32_t seq;
    uint32_t t_us;
    int8_t rssi;
    uint8_t channel;
    bool first_word_invalid;
    float gain;
    int8_t iq[RS_AMP_COUNT * 2]; /* imag, real pairs */
} csi_item_t;

static const rs_config_t *s_cfg;
static QueueHandle_t s_queue;
static uint32_t s_accepted;
static uint32_t s_dropped;
static char s_tx_mac_str[18];

#define MAX_TAG_SLOTS RS_MAX_TAGS
typedef struct {
    char id[RS_TAG_ID_MAX + 1];
    uint32_t heard;
    int32_t rssi_sum;
    int8_t rssi_max;
} tag_slot_t;

static tag_slot_t s_tags[MAX_TAG_SLOTS];
static portMUX_TYPE s_tag_lock = portMUX_INITIALIZER_UNLOCKED;

static void csi_cb(void *ctx, wifi_csi_info_t *info)
{
    (void)ctx;
    if (info == NULL || info->buf == NULL) {
        return;
    }
    /* Privacy: the very first thing we do is drop anything not from our paired transmitter.
     * Nothing about any other device is read, counted, or printed. */
    if (memcmp(info->mac, s_cfg->paired_tx_mac, 6) != 0) {
        return;
    }
    if (info->len < RS_AMP_COUNT * 2 || info->payload == NULL || info->payload_len < RS_SEQ_OFFSET + 4) {
        return;
    }
    const wifi_pkt_rx_ctrl_t *rx = &info->rx_ctrl;

    csi_item_t item;
    memcpy(&item.seq, info->payload + RS_SEQ_OFFSET, sizeof(item.seq));
    item.t_us = rx->timestamp;
    item.rssi = rx->rssi;
    item.channel = rx->channel;
    item.first_word_invalid = info->first_word_invalid;
    item.gain = 1.0f;
#if RS_GAIN_CONTROL
    {
        static uint32_t count;
        uint8_t agc_gain = 0;
        int8_t fft_gain = 0;
        esp_csi_gain_ctrl_get_rx_gain(rx, &agc_gain, &fft_gain);
        if (count < 100) {
            esp_csi_gain_ctrl_record_rx_gain(agc_gain, fft_gain);
        }
        count++;
        esp_csi_gain_ctrl_get_gain_compensation(&item.gain, agc_gain, fft_gain);
    }
#endif
    memcpy(item.iq, info->buf, sizeof(item.iq));

    __atomic_fetch_add(&s_accepted, 1, __ATOMIC_RELAXED);
    if (xQueueSend(s_queue, &item, 0) != pdTRUE) {
        __atomic_fetch_add(&s_dropped, 1, __ATOMIC_RELAXED);
    }
}

static void writer_task(void *arg)
{
    (void)arg;
    csi_item_t item;
    uint8_t amps[RS_AMP_COUNT];
    char line[RS_LINE_MAX];
    for (;;) {
        if (xQueueReceive(s_queue, &item, portMAX_DELAY) != pdTRUE) {
            continue;
        }
        for (int i = 0; i < RS_AMP_COUNT; i++) {
            amps[i] = rs_amplitude(item.iq[2 * i], item.iq[2 * i + 1], item.gain);
        }
        if (item.first_word_invalid) {
            amps[0] = 0; /* the first 4 bytes (2 samples) are not valid on some chips */
            amps[1] = 0;
        }
        size_t n = rs_fmt_csi(line, sizeof(line), s_cfg->node_id, s_cfg->room_id, s_tx_mac_str, item.seq, item.t_us,
                              item.rssi, item.channel, amps);
        rs_out_write(line, n);
    }
}

static void espnow_recv_cb(const esp_now_recv_info_t *info, const uint8_t *data, int len)
{
    if (info == NULL || data == NULL || len != (int)sizeof(rs_tag_packet_t)) {
        return;
    }
    const rs_tag_packet_t *pkt = (const rs_tag_packet_t *)data;
    if (memcmp(pkt->magic, RS_TAG_MAGIC, 4) != 0) {
        return;
    }
    char id[RS_TAG_ID_MAX + 2];
    memcpy(id, pkt->tag_id, RS_TAG_ID_MAX + 1);
    id[RS_TAG_ID_MAX + 1] = '\0';
    if (!rs_list_contains(s_cfg->tags, id)) {
        return; /* only commissioned tags are ever recorded */
    }
    int rssi = info->rx_ctrl != NULL ? info->rx_ctrl->rssi : -127;

    portENTER_CRITICAL(&s_tag_lock);
    tag_slot_t *slot = NULL;
    for (int i = 0; i < MAX_TAG_SLOTS; i++) {
        if (strcmp(s_tags[i].id, id) == 0) {
            slot = &s_tags[i];
            break;
        }
        if (slot == NULL && s_tags[i].id[0] == '\0') {
            slot = &s_tags[i];
        }
    }
    if (slot != NULL) {
        if (slot->id[0] == '\0') {
            strlcpy(slot->id, id, sizeof(slot->id));
            slot->heard = 0;
            slot->rssi_sum = 0;
            slot->rssi_max = -127;
        }
        slot->heard++;
        slot->rssi_sum += rssi;
        if (rssi > slot->rssi_max) {
            slot->rssi_max = (int8_t)rssi;
        }
    }
    portEXIT_CRITICAL(&s_tag_lock);
}

void rs_rx_start(const rs_config_t *cfg)
{
    s_cfg = cfg;
    rs_mac_format(cfg->paired_tx_mac, s_tx_mac_str);
    memset(s_tags, 0, sizeof(s_tags));

    s_queue = xQueueCreate(CONFIG_RS_OUT_QUEUE_LEN, sizeof(csi_item_t));
    configASSERT(s_queue != NULL);
    xTaskCreate(writer_task, "rs_csi_out", 4096, NULL, 5, NULL);

    /* Responder tags arrive as ordinary ESP-NOW broadcasts, handled separately from CSI. */
    ESP_ERROR_CHECK(esp_now_register_recv_cb(espnow_recv_cb));

    /* CSI needs promiscuous mode; csi_cb discards everything except the paired transmitter. */
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));
    wifi_csi_config_t csi = {
        .lltf_en = true,
        .htltf_en = true,
        .stbc_htltf2_en = true,
        .ltf_merge_en = true,
        .channel_filter_en = true,
        .manu_scale = false,
        .shift = false,
    };
    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&csi));
    ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(csi_cb, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_csi(true));
    ESP_LOGI(TAG, "receiving CSI from %s", s_tx_mac_str);
}

uint32_t rs_rx_take_count(void)
{
    return __atomic_exchange_n(&s_accepted, 0, __ATOMIC_RELAXED);
}

uint32_t rs_rx_dropped(void)
{
    return __atomic_load_n(&s_dropped, __ATOMIC_RELAXED);
}

void rs_rx_emit_tag_summaries(const rs_config_t *cfg)
{
    tag_slot_t snapshot[MAX_TAG_SLOTS];
    portENTER_CRITICAL(&s_tag_lock);
    memcpy(snapshot, s_tags, sizeof(snapshot));
    memset(s_tags, 0, sizeof(s_tags));
    portEXIT_CRITICAL(&s_tag_lock);

    char line[RS_LINE_MAX];
    for (int i = 0; i < MAX_TAG_SLOTS; i++) {
        if (snapshot[i].id[0] == '\0' || snapshot[i].heard == 0) {
            continue; /* no summary for a tag that was not heard this second */
        }
        size_t n = rs_fmt_tag(line, sizeof(line), cfg->node_id, cfg->room_id, snapshot[i].id, snapshot[i].heard,
                              snapshot[i].rssi_sum, snapshot[i].rssi_max);
        rs_out_write(line, n);
    }
}
