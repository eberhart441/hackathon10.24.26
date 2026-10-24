#include "rs_radio.h"

#include <string.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_now.h"
#include "esp_wifi.h"

static const char *TAG = "rs_radio";

const unsigned char RS_BROADCAST_MAC[6] = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff};

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
    if (cfg->role == RS_ROLE_TX) {
        /* Same order as the esp-csi csi_send example; receivers recognise this fixed address. */
        ESP_ERROR_CHECK(esp_wifi_set_mac(WIFI_IF_STA, cfg->own_mac));
    }

    ESP_ERROR_CHECK(esp_now_init());
    ESP_LOGI(TAG, "radio up: channel %u, HT20", cfg->channel);
    return ESP_OK;
}

esp_err_t rs_radio_add_broadcast_peer(const rs_config_t *cfg, bool fixed_rate)
{
    esp_now_peer_info_t peer = {0};
    peer.channel = cfg->channel;
    peer.ifidx = WIFI_IF_STA;
    peer.encrypt = false;
    memcpy(peer.peer_addr, RS_BROADCAST_MAC, 6);
    esp_err_t err = esp_now_add_peer(&peer);
    if (err != ESP_OK) {
        return err;
    }
    if (fixed_rate) {
        esp_now_rate_config_t rate = {
            .phymode = WIFI_PHY_MODE_HT20,
            .rate = WIFI_PHY_RATE_MCS0_LGI,
            .ersu = false,
            .dcm = false,
        };
        err = esp_now_set_peer_rate_config(peer.peer_addr, &rate);
    }
    return err;
}
