#include "rs_out.h"

#include <stdarg.h>
#include <stdio.h>

#include "rs_proto.h"

void rs_out_write(const char *line, size_t len)
{
    if (len == 0) {
        return;
    }
    /* A single fwrite holds the stdio lock for the whole line, so lines from different
     * tasks (and ESP_LOG output) cannot interleave inside a record. */
    fwrite(line, 1, len, stdout);
    fflush(stdout);
}

void rs_out_printf(const char *fmt, ...)
{
    char buf[RS_LINE_MAX];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof(buf) - 1, fmt, ap);
    va_end(ap);
    if (n < 0) {
        return;
    }
    if ((size_t)n > sizeof(buf) - 2) {
        n = (int)sizeof(buf) - 2;
    }
    buf[n++] = '\n';
    rs_out_write(buf, (size_t)n);
}
