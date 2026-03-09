#ifndef SC_WEB_SCREENSHOT_H
#define SC_WEB_SCREENSHOT_H

#include "common.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <libavutil/frame.h>

struct sc_web_screenshot {
    uint8_t *png_data;
    size_t png_size;
    char *base64_data;
    size_t base64_size;
    uint16_t width;
    uint16_t height;
};

// Encode an AVFrame (YUV420P or any pixel format) to PNG and base64.
// The caller must call sc_web_screenshot_destroy() to free resources.
bool
sc_web_screenshot_encode(struct sc_web_screenshot *ss, const AVFrame *frame);

void
sc_web_screenshot_destroy(struct sc_web_screenshot *ss);

#endif
