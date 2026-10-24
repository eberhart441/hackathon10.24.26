// STEP 1 for every ESP32: flash this first, open Serial Monitor at 115200.
// It tells you exactly which chip you hold (classic ESP32 vs S3/C3), its flash size and its MAC.
// Then put a piece of tape on the board with its MAC and role (GW, R1, R2, R3, R4, SP).
//
// Arduino IDE: Tools > Board > "ESP32 Dev Module" (works for the Inland ESP32-WROOM-32D boards),
// Tools > Port > the COM port that appears when you plug the board in.
// If upload hangs on "Connecting....", hold the BOOT button until it starts.

#include <WiFi.h>

#ifndef LED_BUILTIN
#define LED_BUILTIN 2  // most classic ESP32 dev boards have the LED on GPIO 2
#endif

void setup() {
  Serial.begin(115200);
  delay(1500);
  pinMode(LED_BUILTIN, OUTPUT);
  WiFi.mode(WIFI_STA);  // required before the MAC address is available
  delay(100);

  Serial.println();
  Serial.println("=== BOARD CHECK ===");
  Serial.printf("chip=%s  revision=%d  cores=%d  cpu_mhz=%u\n", ESP.getChipModel(), (int)ESP.getChipRevision(),
                (int)ESP.getChipCores(), (unsigned)ESP.getCpuFreqMHz());
  Serial.printf("flash_mb=%u  sdk=%s\n", (unsigned)(ESP.getFlashChipSize() / (1024 * 1024)), ESP.getSdkVersion());
  Serial.printf("mac=%s\n", WiFi.macAddress().c_str());
  Serial.println("Write the MAC and the role on tape on the board.");
}

void loop() {
  digitalWrite(LED_BUILTIN, HIGH);
  delay(150);
  digitalWrite(LED_BUILTIN, LOW);
  delay(850);
  static int n = 0;
  if (++n % 5 == 0) Serial.printf("# alive, mac=%s\n", WiFi.macAddress().c_str());
}
