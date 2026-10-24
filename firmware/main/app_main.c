/* Beacon node firmware: one image for the transmitter, receiver, and responder tag.
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
#include "rs_relay.h"
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
    char paired[18];
    rs_mac_format(s_live.paired_tx, paired);
    for (;;) {
        vTaskDelayUntil(&last, pdMS_TO_TICKS(1000));

        /* Receivers only: transmitters and tags have no serial link to the hub at runtime and
         * send no heartbeat (requirement 3.5). The hub infers their health from this line. */
        uint32_t uptime_ms = (uint32_t)(esp_timer_get_time() / 1000);
        /* csi_q_drops counts every record this receiver could not deliver: output-queue drops
         * plus, when relaying, lines the relay could not get to the master. */
        size_t n = rs_fmt_hb(line, sizeof(line), s_live.node_id, s_live.room_id, paired, CONFIG_RS_FW_VERSION,
                             uptime_ms, rs_rx_take_count(), esp_get_free_heap_size(),
                             rs_rx_dropped() + rs_relay_dropped(), "HUB");
        rs_data_write(line, n);
        rs_rx_emit_tag_summaries(&s_live);
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

    rs_console_start(&s_live, &s_pending);
    ESP_ERROR_CHECK(rs_radio_start(&s_live));

    switch (s_live.role) {
    case RS_ROLE_TX:
        rs_tx_start(&s_live);
        rs_relay_start_gateway(&s_live); /* only if relays are configured */
        break;
    case RS_ROLE_RX:
        rs_relay_init_sender(&s_live); /* only if relay_to is set */
        rs_rx_start(&s_live);
        xTaskCreate(report_task, "rs_report", 4096, NULL, 5, NULL);
        break;
    default:
        rs_tag_start(&s_live);
        break;
    }
}
