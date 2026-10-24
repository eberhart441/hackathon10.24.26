#pragma once
/* One place that writes protocol lines to the console, so a record is never split
 * by another record or by a log line. */

#include <stddef.h>

/* Write `len` bytes (a complete line ending in '\n') with a single call. */
void rs_out_write(const char *line, size_t len);

/* Format and write a reply such as "OK,CFG,node_id". */
void rs_out_printf(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
