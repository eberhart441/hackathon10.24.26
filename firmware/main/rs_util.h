#pragma once
/* Small pure helpers (no ESP-IDF calls) so they stay easy to reason about and test. */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define RS_AMP_COUNT 64 /* amplitudes per CSI record: the 64 L-LTF subcarriers as captured */

/* Letters, digits, '_' and '-'; 1..max_len characters. */
bool rs_valid_name(const char *s, size_t max_len);

/* Parse "aa:bb:cc:dd:ee:ff" (either case) into 6 bytes. */
bool rs_mac_parse(const char *s, uint8_t out[6]);

/* Format as lowercase "aa:bb:cc:dd:ee:ff". `out` must hold 18 bytes. */
void rs_mac_format(const uint8_t mac[6], char out[18]);

bool rs_mac_is_broadcast(const uint8_t mac[6]);

/* sqrt(imag^2 + real^2) scaled by `gain`, clipped to 0..255. */
uint8_t rs_amplitude(int8_t imag, int8_t real, float gain);

/* True if `id` is one of the comma-separated names in `list`. */
bool rs_list_contains(const char *list, const char *id);

/* True if `list` is empty or a comma-separated list of valid tag IDs (1 to 4 characters each),
 * with at most `max_items` entries. */
bool rs_valid_tag_list(const char *list, size_t max_items);
