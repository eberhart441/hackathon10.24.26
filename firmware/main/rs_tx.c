#include "rs_tx.h"

#include <string.h>

#include "esp_log.h"
#include "esp_now.h"
#include "esp_timer.h"

#include "rs_radio.h"

static const char *TAG = "rs_tx";

static uint8_t s_peer[6];       /* the paired receiver (or broadcast) */
static uint32_t s_seq;          /* the counter that goes in every packet */
static esp_timer_handle_t s_timer;

static void send_cb(void *arg)
{
    (void)arg;
    uint32_t seq = s_seq++;
    /* The payload is just the counter (esp-csi csi_send format). The receiver reads it back
     * at a fixed offset in the frame. A failed send shows up at the receiver as a seq gap. */
    esp_now_send(s_peer, (const uint8_t *)&seq, sizeof(seq));
}

void rs_tx_start(const rs_config_t *cfg)
{
    memcpy(s_peer, cfg->peer, 6);
    /* Unicast to the paired receiver at HT MCS0 (requirement 2.1). */
    ESP_ERROR_CHECK(rs_radio_add_peer(s_peer, cfg->channel, true));
    const esp_timer_create_args_t args = {.callback = send_cb, .name = "rs_tx"};
    ESP_ERROR_CHECK(esp_timer_create(&args, &s_timer));
    ESP_ERROR_CHECK(esp_timer_start_periodic(s_timer, 1000000ULL / cfg->pps));
    ESP_LOGI(TAG, "transmitting %u packets/s", cfg->pps);
}
