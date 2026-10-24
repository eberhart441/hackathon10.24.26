/* RoomSense node firmware: one image for the transmitter, receiver, and responder tag.
 * The role and names live in flash and are set over serial (see firmware/docs/serial-protocol.md).
 *
 * CSI capture is based on Espressif's esp-csi csi_send / csi_recv examples
 * (Apache-2.0, https://github.com/espressif/esp-csi).
 */
#include <stdio.h>

#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "sdkconfig.h"

#include "rs_config.h"
#include "rs_console.h"
#include "rs_out.h"
#include "rs_proto.h"
#include "rs_radio.h"
#include "rs_rx.h"
#include "rs_tag.h"
#include "rs_tx.h"

static rs_config_t s_live;    /* what this boot is running with */
static rs_config_t s_pending; /* what CFG SET edits; takes effect after a reboot */

static void report_task(void *arg)
{
    (void)arg;
    TickType_t last = xTaskGetTickCount();
    char line[RS_LINE_MAX];
    for (;;) {
        vTaskDelayUntil(&last, pdMS_TO_TICKS(1000));

        unsigned pps = 0;
        uint32_t dropped = 0;
        switch (s_live.role) {
        case RS_ROLE_TX:
            pps = rs_tx_take_count();
            break;
        case RS_ROLE_RX:
            pps = rs_rx_take_count();
            dropped = rs_rx_dropped();
            break;
        default:
            pps = rs_tag_take_count();
            break;
        }
        uint32_t uptime_ms = (uint32_t)(esp_timer_get_time() / 1000);
        size_t n = rs_fmt_hb(line, sizeof(line), s_live.node_id, rs_role_name(s_live.role), s_live.room_id, uptime_ms,
                             pps, s_live.channel, dropped);
        rs_out_write(line, n);

        if (s_live.role == RS_ROLE_RX) {
            rs_rx_emit_tag_summaries(&s_live);
        }
    }
}

void app_main(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

    rs_config_load(&s_live);
    s_pending = s_live;

    char line[RS_LINE_MAX];
    size_t n = rs_fmt_boot(line, sizeof(line), s_live.node_id, rs_role_name(s_live.role), s_live.room_id,
                           CONFIG_RS_FW_VERSION, s_live.channel, "HT20");
    rs_out_write(line, n);

    rs_console_start(&s_live, &s_pending);
    ESP_ERROR_CHECK(rs_radio_start(&s_live));

    switch (s_live.role) {
    case RS_ROLE_TX:
        rs_tx_start(&s_live);
        break;
    case RS_ROLE_RX:
        rs_rx_start(&s_live);
        break;
    default:
        rs_tag_start(&s_live);
        break;
    }

    xTaskCreate(report_task, "rs_report", 4096, NULL, 5, NULL);
}
