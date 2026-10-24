#include "rs_radio.h"

#include <string.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_now.h"
#include "esp_wifi.h"

static const char *TAG = "rs_radio";

const uint8_t RS_BROADCAST_MAC[6] = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff};

esp_err_t rs_radio_start(const rs_config_t *cfg)
{
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_bandwidth(WIFI_IF_STA, WIFI_BW20));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    ESP_ERROR_CHECK(esp_wifi_set_channel(cfg->channel, WIFI_SECOND_CHAN_NONE));

    ESP_ERROR_CHECK(esp_now_init());
    ESP_LOGI(TAG, "radio up: channel %u, 20 MHz", cfg->channel);
    return ESP_OK;
}

esp_err_t rs_radio_add_peer(const uint8_t mac[6], uint8_t channel, bool fixed_rate, wifi_phy_rate_t rate)
{
    esp_now_peer_info_t peer = {0};
    peer.channel = channel;
    peer.ifidx = WIFI_IF_STA;
    peer.encrypt = false;
    memcpy(peer.peer_addr, mac, 6);
    esp_err_t err = esp_now_add_peer(&peer);
    if (err != ESP_OK) {
        return err;
    }
    if (fixed_rate) {
        esp_now_rate_config_t rate_cfg = {
            .phymode = WIFI_PHY_MODE_HT20,
            .rate = rate,
            .ersu = false,
            .dcm = false,
        };
        err = esp_now_set_peer_rate_config(peer.peer_addr, &rate_cfg);
    }
    return err;
}
