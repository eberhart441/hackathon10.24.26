#include "rs_tag.h"

#include <string.h>

#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_now.h"
#include "esp_random.h"
#include "esp_task_wdt.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

#include "rs_radio.h"
#include "rs_tag_packet.h"

static const char *TAG = "rs_tag";

#define JITTER_MS 20 /* +/- random offset on every interval (requirement 23.2) */
#define LED_ON_MS 20

static const rs_config_t *s_cfg;

static void tag_task(void *arg)
{
    (void)arg;
    /* Requirement 23.6: if this task ever hangs, the watchdog reboots the tag. */
    ESP_ERROR_CHECK(esp_task_wdt_add(NULL));

    rs_tag_packet_t pkt;
    memset(&pkt, 0, sizeof(pkt));
    memcpy(pkt.magic, RS_TAG_MAGIC, 4);
    memcpy(pkt.tag_id, s_cfg->tag_id, strnlen(s_cfg->tag_id, sizeof(pkt.tag_id)));

    const int base_ms = 1000 / (s_cfg->pps ? s_cfg->pps : 10);
    for (;;) {
        pkt.seq++;
        pkt.uptime_ms = (uint32_t)(esp_timer_get_time() / 1000);
        esp_now_send(RS_BROADCAST_MAC, (const uint8_t *)&pkt, sizeof(pkt));
#if CONFIG_RS_TAG_LED_GPIO >= 0
        gpio_set_level(CONFIG_RS_TAG_LED_GPIO, 1);
        vTaskDelay(pdMS_TO_TICKS(LED_ON_MS));
        gpio_set_level(CONFIG_RS_TAG_LED_GPIO, 0);
        int wait_ms = base_ms - LED_ON_MS;
#else
        int wait_ms = base_ms;
#endif
        int jitter = (int)(esp_random() % (2 * JITTER_MS + 1)) - JITTER_MS;
        wait_ms += jitter;
        if (wait_ms < 5) {
            wait_ms = 5;
        }
        vTaskDelay(pdMS_TO_TICKS(wait_ms));
        esp_task_wdt_reset();
    }
}

void rs_tag_start(const rs_config_t *cfg)
{
    s_cfg = cfg;
    ESP_ERROR_CHECK(rs_radio_add_peer(RS_BROADCAST_MAC, cfg->channel, false, WIFI_PHY_RATE_MCS0_LGI));
#if CONFIG_RS_TAG_LED_GPIO >= 0
    gpio_config_t io = {
        .pin_bit_mask = 1ULL << CONFIG_RS_TAG_LED_GPIO,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&io));
#endif
    xTaskCreate(tag_task, "rs_tag", 3072, NULL, 5, NULL);
    ESP_LOGI(TAG, "tag %s broadcasting about %u/s", cfg->tag_id, cfg->pps);
}
