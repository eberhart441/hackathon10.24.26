#include "rs_console.h"

#include <stdio.h>
#include <string.h>

#include "esp_log.h"
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

static void handle_line(char *line)
{
    char *save = NULL;
    char *cmd = strtok_r(line, " \t", &save);
    if (cmd == NULL) {
        return;
    }
    if (strcmp(cmd, "PING") == 0) {
        rs_out_printf("PONG,%s", s_live->node_id);
    } else if (strcmp(cmd, "CFG") == 0) {
        char *sub = strtok_r(NULL, " \t", &save);
        if (sub == NULL) {
            rs_out_printf("ERR,CFG,usage");
        } else if (strcmp(sub, "GET") == 0) {
            char body[RS_LINE_MAX - 8];
            rs_config_format(s_pending, body, sizeof(body));
            rs_out_printf("CFG,%s", body);
        } else if (strcmp(sub, "SET") == 0) {
            char *key = strtok_r(NULL, " \t", &save);
            char *value = strtok_r(NULL, " \t", &save);
            const char *err = NULL;
            if (key == NULL || value == NULL) {
                rs_out_printf("ERR,CFG,usage");
            } else if (!rs_config_set(s_pending, key, value, &err)) {
                rs_out_printf("ERR,CFG,%s", err ? err : "invalid");
            } else if (rs_config_save(s_pending) != ESP_OK) {
                rs_out_printf("ERR,CFG,save_failed");
            } else {
                rs_out_printf("OK,CFG,%s", key);
            }
        } else if (strcmp(sub, "RESET") == 0) {
            rs_config_defaults(s_pending);
            if (rs_config_erase() == ESP_OK) {
                rs_out_printf("OK,CFG,RESET");
            } else {
                rs_out_printf("ERR,CFG,save_failed");
            }
        } else {
            rs_out_printf("ERR,CFG,usage");
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
