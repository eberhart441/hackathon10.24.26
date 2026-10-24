#include "rs_console.h"

#include <stdio.h>
#include <string.h>

#include "esp_log.h"
#include "esp_mac.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

#if CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG
#include "driver/usb_serial_jtag.h"
#else
#include "driver/uart.h"
#endif

#include "rs_out.h"
#include "rs_proto.h"
#include "rs_util.h"

static const char *TAG = "rs_console";

#define LINE_MAX_CHARS 120

static const rs_config_t *s_live;
static rs_config_t *s_pending;

static int read_byte(void)
{
    uint8_t c;
#if CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG
    int n = usb_serial_jtag_read_bytes(&c, 1, pdMS_TO_TICKS(50));
#else
    int n = uart_read_bytes(CONFIG_ESP_CONSOLE_UART_NUM, &c, 1, pdMS_TO_TICKS(50));
#endif
    return n == 1 ? (int)c : -1;
}

static void print_config(void)
{
    char mac[18];
    uint8_t factory[6];
    const rs_config_t *c = s_pending;

    rs_out_printf("CFG,node_id=%s", c->node_id);
    rs_out_printf("CFG,room_id=%s", c->room_id);
    rs_out_printf("CFG,role=%s", rs_role_name(c->role));
    rs_out_printf("CFG,channel=%u", c->channel);
    rs_out_printf("CFG,pps=%u", c->pps);
    rs_mac_format(c->peer, mac);
    rs_out_printf("CFG,peer=%s", mac);
    rs_mac_format(c->paired_tx, mac);
    rs_out_printf("CFG,paired_tx=%s", mac);
    rs_out_printf("CFG,tag_id=%s", c->tag_id);
    rs_out_printf("CFG,tags=%s", c->tags);
    rs_out_printf("CFG,rx_mode=HUB");
    if (esp_read_mac(factory, ESP_MAC_WIFI_STA) == ESP_OK) {
        rs_mac_format(factory, mac);
        rs_out_printf("CFG,mac=%s", mac); /* what a paired receiver should use as paired_tx */
    }
    rs_out_printf("CFG,fw_version=%s", CONFIG_RS_FW_VERSION);
}

/* SET key=value [key=value ...]: each pair is validated and saved on its own. */
static void handle_set(char *args)
{
    char *save = NULL;
    char *pair = strtok_r(args, " \t", &save);
    if (pair == NULL) {
        rs_out_printf("ERR,SET,usage");
        return;
    }
    for (; pair != NULL; pair = strtok_r(NULL, " \t", &save)) {
        char *eq = strchr(pair, '=');
        if (eq == NULL || eq == pair) {
            rs_out_printf("ERR,SET,usage");
            continue;
        }
        *eq = '\0';
        const char *key = pair;
        const char *value = eq + 1;
        const char *err = NULL;
        if (!rs_config_set(s_pending, key, value, &err)) {
            rs_out_printf("ERR,SET,%s", err ? err : "invalid");
        } else if (rs_config_save(s_pending) != ESP_OK) {
            rs_out_printf("ERR,SET,save_failed");
        } else {
            rs_out_printf("OK,SET,%s", key);
        }
    }
}

static void handle_line(char *line)
{
    /* Lines the hub sends to every receiver (CMD,ALARM,... etc.) are for EDGE_Mode; in
     * HUB_Mode they are ignored silently. */
    if (strncmp(line, "CMD,", 4) == 0) {
        return;
    }
    char *save = NULL;
    char *cmd = strtok_r(line, " \t", &save);
    if (cmd == NULL) {
        return;
    }
    if (strcmp(cmd, "PING") == 0) {
        rs_out_printf("PONG,%s", s_live->node_id);
    } else if (strcmp(cmd, "GET") == 0) {
        print_config();
    } else if (strcmp(cmd, "SET") == 0) {
        handle_set(save ? save : (char *)"");
    } else if (strcmp(cmd, "FACTORY_RESET") == 0) {
        rs_config_defaults(s_pending);
        if (rs_config_erase() == ESP_OK) {
            rs_out_printf("OK,FACTORY_RESET");
        } else {
            rs_out_printf("ERR,FACTORY_RESET,failed");
        }
    } else if (strcmp(cmd, "REBOOT") == 0) {
        rs_out_printf("OK,REBOOT");
        vTaskDelay(pdMS_TO_TICKS(100));
        esp_restart();
    } else {
        rs_out_printf("ERR,CMD,unknown");
    }
}

static void console_task(void *arg)
{
    (void)arg;
    char line[LINE_MAX_CHARS + 1];
    size_t len = 0;
    bool overflow = false;
    for (;;) {
        int c = read_byte();
        if (c < 0) {
            continue;
        }
        if (c == '\n' || c == '\r') {
            if (overflow) {
                rs_out_printf("ERR,CMD,too_long");
            } else if (len > 0) {
                line[len] = '\0';
                handle_line(line);
            }
            len = 0;
            overflow = false;
        } else if (len < LINE_MAX_CHARS) {
            line[len++] = (char)c;
        } else {
            overflow = true;
        }
    }
}

void rs_console_start(const rs_config_t *live, rs_config_t *pending)
{
    s_live = live;
    s_pending = pending;
#if CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG
    usb_serial_jtag_driver_config_t usb_cfg = USB_SERIAL_JTAG_DRIVER_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&usb_cfg));
#else
    ESP_ERROR_CHECK(uart_driver_install(CONFIG_ESP_CONSOLE_UART_NUM, 256, 0, 0, NULL, 0));
#endif
    xTaskCreate(console_task, "rs_console", 3072, NULL, 4, NULL);
    ESP_LOGI(TAG, "listening for commands");
}
