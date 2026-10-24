// GATEWAY: receives every room node's ESP-NOW packet and prints it as one serial line per packet,
// in the same key=value format as the rest of the kit:
//   n=2,seq=118,pir=1,rad=0,d=-1,sm=0,x=0,rssi=-51
// Plug this board into the laptop. The web dashboard (Connect board) and python/link_test.py both read it.
// Lines starting with "#" are comments the dashboard ignores.
//
// Needs the ESP32 Arduino core. Works with core 2.x and 3.x (the receive-callback signature changed in 3.x).
// RSSI (signal strength of each packet) is only reported on core 3.x; on 2.x it prints rssi=0.

#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

#define WIFI_CHANNEL 1  // must match every room node

typedef struct __attribute__((packed)) {
  uint8_t magic;
  uint8_t node;
  uint32_t seq;
  uint8_t pir;
  uint8_t radar;
  uint16_t dist_cm;
  uint16_t crossings;
  uint16_t since_motion_s;
  uint32_t uptime_s;
} Packet;

typedef struct {
  Packet p;
  int8_t rssi;
} Item;

static QueueHandle_t rxQueue;

// Runs in the Wi-Fi task: do the minimum (copy into a queue). Printing happens in loop().
static void handle(const uint8_t *data, int len, int rssi) {
  if (data == nullptr || len != (int)sizeof(Packet)) return;  // validate length before touching the buffer
  Item it;
  memcpy(&it.p, data, sizeof(Packet));
  if (it.p.magic != 0xA7) return;  // ignore stray/foreign ESP-NOW traffic
  it.rssi = (int8_t)rssi;
  xQueueSend(rxQueue, &it, 0);  // drop if the queue is full rather than block the radio
}

#if ESP_ARDUINO_VERSION_MAJOR >= 3
void onRecv(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
  handle(data, len, info->rx_ctrl ? info->rx_ctrl->rssi : 0);
}
#else
void onRecv(const uint8_t *mac, const uint8_t *data, int len) {
  handle(data, len, 0);
}
#endif

void setup() {
  Serial.begin(115200);
  rxQueue = xQueueCreate(64, sizeof(Item));

  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_promiscuous(true);
  esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);
  esp_wifi_set_promiscuous(false);

  if (esp_now_init() != ESP_OK) {
    Serial.println("# esp_now_init FAILED, restarting");
    delay(2000);
    ESP.restart();
  }
  esp_now_register_recv_cb(onRecv);
  Serial.printf("# gateway up, mac %s, channel %d, waiting for nodes\n", WiFi.macAddress().c_str(), WIFI_CHANNEL);
}

void loop() {
  Item it;
  while (xQueueReceive(rxQueue, &it, 0) == pdTRUE) {
    const Packet &p = it.p;
    Serial.printf("n=%d,seq=%u,pir=%d,rad=%d,d=%d,sm=%d,x=%u,rssi=%d\n", p.node, (unsigned)p.seq, p.pir, p.radar,
                  p.dist_cm == 0xFFFF ? -1 : (int)p.dist_cm, p.since_motion_s == 0xFFFF ? -1 : (int)p.since_motion_s,
                  (unsigned)p.crossings, (int)it.rssi);
  }
  static uint32_t lastBeat = 0;
  if (millis() - lastBeat > 5000) {
    lastBeat = millis();
    Serial.printf("# gateway alive, uptime %us\n", (unsigned)(millis() / 1000));
  }
  delay(2);
}
