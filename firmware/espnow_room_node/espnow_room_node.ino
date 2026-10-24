// ROOM NODE: reads presence sensors and broadcasts a small packet to the gateway over ESP-NOW.
// ESP-NOW is Espressif's peer-to-peer radio protocol: no router, no Wi-Fi password, no internet.
// That matters for the evacuation story: the network keeps working when the building's Wi-Fi dies.
//
// FLASH THIS 4-5 TIMES: change NODE_ID below for each board (1, 2, 3, 4, and 5 for the spare/hallway).
// Keep the Packet struct identical in espnow_gateway.ino.
//
// WIRING (classic ESP32 dev board, all 3.3 V logic):
//   PIR  (HC-SR501)  OUT -> GPIO 27, VCC -> VIN (5 V), GND -> GND.  Needs ~60 s warm-up after power-on.
//   Radar (LD2410)   OUT -> GPIO 26, VCC -> 5 V, GND -> GND.  Optional. Reads LOW if not connected.
//   Ultrasonic (HC-SR04, optional door sensor, set USE_ULTRASONIC 1):
//        TRIG -> GPIO 25, VCC -> 5 V, GND -> GND,
//        ECHO -> GPIO 33 THROUGH A VOLTAGE DIVIDER (ECHO -- 1k --+-- GPIO33, +-- 2k -- GND).
//        The HC-SR04 echo pin outputs 5 V and the ESP32 pins are NOT 5 V tolerant. Skipping the divider can damage the board.
//
// ABOUT THE DOOR SENSOR: one ultrasonic sensor can COUNT crossings but cannot tell entering from leaving.
// Direction needs two sensors in sequence. Treat "crossings" as "someone passed", not as a headcount.

#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

// ===== CONFIG =====
#define NODE_ID 1             // <-- change per board
#define WIFI_CHANNEL 1        // must match the gateway; try 1, 6 or 11 if the venue is crowded
#define USE_ULTRASONIC 0      // 1 = enable the HC-SR04 door sensor
const int PIN_PIR = 27;
const int PIN_RADAR = 26;
const int PIN_TRIG = 25;
const int PIN_ECHO = 33;
const int PIN_LED = 2;
const uint16_t CROSS_CM = 80;  // closer than this = someone is in the doorway

typedef struct __attribute__((packed)) {
  uint8_t magic;            // 0xA7, lets the gateway ignore stray packets
  uint8_t node;
  uint32_t seq;             // increments every packet; gaps = lost packets
  uint8_t pir;
  uint8_t radar;
  uint16_t dist_cm;         // 0xFFFF = no echo / sensor disabled
  uint16_t crossings;
  uint16_t since_motion_s;  // seconds since PIR or radar last fired; 0xFFFF = never
  uint32_t uptime_s;
} Packet;

static const uint8_t BROADCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
static uint32_t seqNum = 0;
static uint16_t crossings = 0;

#if USE_ULTRASONIC
uint16_t readDistanceCm() {
  digitalWrite(PIN_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);
  unsigned long us = pulseIn(PIN_ECHO, HIGH, 25000UL);  // 25 ms timeout (~4 m)
  if (us == 0) return 0xFFFF;
  return (uint16_t)(us / 58);
}
#endif

void setup() {
  Serial.begin(115200);
  pinMode(PIN_PIR, INPUT);
  pinMode(PIN_RADAR, INPUT_PULLDOWN);
  pinMode(PIN_LED, OUTPUT);
#if USE_ULTRASONIC
  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);
#endif

  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  // Toggling promiscuous mode is the standard trick that makes set_channel stick on the ESP32 Arduino core.
  esp_wifi_set_promiscuous(true);
  esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);
  esp_wifi_set_promiscuous(false);

  if (esp_now_init() != ESP_OK) {
    Serial.println("# esp_now_init FAILED, restarting");
    delay(2000);
    ESP.restart();
  }
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BROADCAST, 6);
  peer.channel = WIFI_CHANNEL;
  peer.encrypt = false;
  if (esp_now_add_peer(&peer) != ESP_OK) Serial.println("# esp_now_add_peer FAILED");

  Serial.printf("# room node %d up, mac %s, channel %d\n", NODE_ID, WiFi.macAddress().c_str(), WIFI_CHANNEL);
}

void loop() {
  static uint32_t lastSampleMs = 0, lastSendMs = 0, lastMotionMs = 0;
  static bool everMoved = false;
  static uint8_t prevPir = 0, prevRadar = 0;
  static uint16_t lastDist = 0xFFFF, curDist = 0xFFFF;

  uint32_t now = millis();
  if (now - lastSampleMs < 100) return;  // sample at 10 Hz
  lastSampleMs = now;

  uint8_t pir = digitalRead(PIN_PIR);
  uint8_t radar = digitalRead(PIN_RADAR);
  if (pir || radar) {
    lastMotionMs = now;
    everMoved = true;
  }

#if USE_ULTRASONIC
  curDist = readDistanceCm();
  if (curDist < CROSS_CM && lastDist >= CROSS_CM) crossings++;
  lastDist = curDist;
#endif

  bool changed = (pir != prevPir) || (radar != prevRadar);
  prevPir = pir;
  prevRadar = radar;

  // Send once a second, and immediately when a presence sensor changes.
  if (changed || now - lastSendMs >= 1000) {
    lastSendMs = now;
    Packet p;
    p.magic = 0xA7;
    p.node = NODE_ID;
    p.seq = seqNum++;
    p.pir = pir;
    p.radar = radar;
    p.dist_cm = curDist;
    p.crossings = crossings;
    if (!everMoved) {
      p.since_motion_s = 0xFFFF;  // never seen motion since boot
    } else {
      uint32_t since = (now - lastMotionMs) / 1000;
      p.since_motion_s = since > 0xFFFE ? 0xFFFE : (uint16_t)since;
    }
    p.uptime_s = now / 1000;

    esp_now_send(BROADCAST, (const uint8_t *)&p, sizeof(p));

    digitalWrite(PIN_LED, HIGH);  // short blink = packet sent
    Serial.printf("n=%d,seq=%u,pir=%d,rad=%d,d=%d,sm=%d,x=%u\n", NODE_ID, (unsigned)p.seq, pir, radar,
                  p.dist_cm == 0xFFFF ? -1 : (int)p.dist_cm, p.since_motion_s == 0xFFFF ? -1 : (int)p.since_motion_s,
                  (unsigned)crossings);
    delay(5);
    digitalWrite(PIN_LED, LOW);
  }
}
