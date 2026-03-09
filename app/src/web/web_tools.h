#ifndef SC_WEB_TOOLS_H
#define SC_WEB_TOOLS_H

#include "common.h"

#include <stdbool.h>
#include <stdint.h>

struct sc_controller;

struct sc_web_tools {
    struct sc_controller *controller;
    uint16_t screen_width;   // screenshot coordinate space (downscaled)
    uint16_t screen_height;  // screenshot coordinate space (downscaled)
    uint16_t frame_width;    // original video frame size
    uint16_t frame_height;   // original video frame size
};

void
sc_web_tools_init(struct sc_web_tools *tools, struct sc_controller *controller,
                  uint16_t screen_width, uint16_t screen_height);

void
sc_web_tools_set_screen_size(struct sc_web_tools *tools,
                             uint16_t width, uint16_t height);

void
sc_web_tools_set_frame_size(struct sc_web_tools *tools,
                            uint16_t width, uint16_t height);

// Returns the OpenAI function calling tools JSON array string.
// The returned string is statically allocated, do not free.
const char *
sc_web_tools_get_definitions(void);

// Execute a tool call. Returns a result string (caller must free).
char *
sc_web_tools_execute(struct sc_web_tools *tools,
                     const char *function_name,
                     const char *arguments_json);

#endif
