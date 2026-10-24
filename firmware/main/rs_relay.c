#include "rs_relay.h"

#include <string.h>

#include "esp_log.h"
#include "esp_now.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

#include "rs_out.h"
#include "rs_radio.h"
#include "rs_util.h"

static const char *TAG = "rs_relay";

#define RELAY_MAX ESP_NOW_MAX_DATA_LEN_V2 /* 1470 bytes per frame: about 4 CSI lines */
#define FLUSH_MS 100                      /* heartbeats and tag lines wait at most this long */
#define RING 32

/* ------------------------------------------------------------------ receiver side */

static bool s_enabled;
static uint8_t s_dest[6];
static SemaphoreHandle_t s_lock;
static uint8_t s_buf[RELAY_MAX];
static size_t s_len;
static uint8_t s_lines;
static uint32_t s_dropped;

/* Line counts of frames in flight, so a frame that is not acknowledged counts its lines as dropped.
 * One producer (whoever holds s_lock) and one consumer (the WiFi task's send callback). */
static uint8_t s_ring[RING];
static volatile uint32_t s_head, s_tail;

static void send_cb(const esp_now_send_info_t *info, esp_now_send_status_t status)
{
    (void)info;
    if (s_tail == s_head) {
        return; /* a frame sent by someone else (not expected on a receiver) */
    }
    uint8_t lines = s_ring[s_tail % RING];
    s_tail++;
    if (status != ESP_NOW_SEND_SUCCESS) {
        __atomic_fetch_add(&s_dropped, lines, __ATOMIC_RELAXED);
    }
}

/* Caller holds s_lock. */
static void send_locked(void)
{
    if (s_lines == 0) {
        return;
    }
    if (s_head - s_tail >= RING) {
        __atomic_fetch_add(&s_dropped, s_lines, __ATOMIC_RELAXED); /* too many frames in flight */
    } else {
        s_ring[s_head % RING] = s_lines;
        s_head++;
        if (esp_now_send(s_dest, s_buf, s_len) != ESP_OK) {
            s_head--;
            __atomic_fetch_add(&s_dropped, s_lines, __ATOMIC_RELAXED);
        }
    }
    s_len = 4;
    s_lines = 0;
}

static void flush_task(void *arg)
{
    (void)arg;
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(FLUSH_MS));
        xSemaphoreTake(s_lock, portMAX_DELAY);
        send_locked();
        xSemaphoreGive(s_lock);
    }
}

void rs_relay_init_sender(const rs_config_t *cfg)
{
    if (rs_mac_is_zero(cfg->relay_to)) {
        return;
    }
    memcpy(s_dest, cfg->relay_to, 6);
    memcpy(s_buf, RS_RELAY_MAGIC, 4);
    s_len = 4;
    s_lock = xSemaphoreCreateMutex();
    configASSERT(s_lock != NULL);
    /* A fast rate keeps each 1.4 KB frame short on air (about 0.3 ms), so it barely disturbs sensing. */
    ESP_ERROR_CHECK(rs_radio_add_peer(s_dest, cfg->channel, true, WIFI_PHY_RATE_MCS4_LGI));
    ESP_ERROR_CHECK(esp_now_register_send_cb(send_cb));
    xTaskCreate(flush_task, "rs_relay", 3072, NULL, 5, NULL);
    s_enabled = true;
    char mac[18];
    rs_mac_format(s_dest, mac);
    ESP_LOGW(TAG, "relaying data to %s; this serial port now shows command replies only", mac);
}

void rs_data_write(const char *line, size_t len)
{
    if (!s_enabled) {
        rs_out_write(line, len);
        return;
    }
    if (len == 0 || len > RELAY_MAX - 4) {
        return;
    }
    xSemaphoreTake(s_lock, portMAX_DELAY);
    if (s_len + len > RELAY_MAX) {
        send_locked();
    }
    memcpy(s_buf + s_len, line, len);
    s_len += len;
    s_lines++;
    xSemaphoreGive(s_lock);
}

uint32_t rs_relay_dropped(void)
{
    return __atomic_load_n(&s_dropped, __ATOMIC_RELAXED);
}

/* ------------------------------------------------------------------ master (gateway) side */

typedef struct {
    uint16_t len;
    uint8_t data[RELAY_MAX];
} frame_t;

static const rs_config_t *s_gw_cfg;
static QueueHandle_t s_frames;
static frame_t s_rx_frame; /* filled in the WiFi task, which runs one callback at a time */

static bool allowed(const uint8_t *mac)
{
    for (int i = 0; i < s_gw_cfg->relay_count; i++) {
        if (memcmp(s_gw_cfg->relays[i], mac, 6) == 0) {
            return true;
        }
    }
    return false;
}

static void gateway_recv_cb(const esp_now_recv_info_t *info, const uint8_t *data, int len)
{
    if (info == NULL || data == NULL || len <= 4 || len > RELAY_MAX || memcmp(data, RS_RELAY_MAGIC, 4) != 0) {
        return;
    }
    if (!allowed(info->src_addr)) {
        return; /* only listed receivers are ever printed */
    }
    s_rx_frame.len = (uint16_t)(len - 4);
    memcpy(s_rx_frame.data, data + 4, (size_t)(len - 4));
    xQueueSend(s_frames, &s_rx_frame, 0); /* if the printer is behind, drop the frame (shows as a seq gap) */
}

static void gateway_task(void *arg)
{
    (void)arg;
    static frame_t f;
    for (;;) {
        if (xQueueReceive(s_frames, &f, portMAX_DELAY) != pdTRUE) {
            continue;
        }
        if (f.len > 0 && f.data[f.len - 1] == '\n') { /* whole lines only, never a partial record */
            rs_out_write((const char *)f.data, f.len);
        }
    }
}

void rs_relay_start_gateway(const rs_config_t *cfg)
{
    if (cfg->relay_count == 0) {
        return;
    }
    s_gw_cfg = cfg;
    s_frames = xQueueCreate(8, sizeof(frame_t));
    configASSERT(s_frames != NULL);
    xTaskCreate(gateway_task, "rs_gateway", 3072, NULL, 5, NULL);
    ESP_ERROR_CHECK(esp_now_register_recv_cb(gateway_recv_cb));
    ESP_LOGW(TAG, "printing relayed data from %u receiver(s)", cfg->relay_count);
}
