#ifndef SC_AI_OCR_H
#define SC_AI_OCR_H

#include "common.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "util/process.h"

#define SC_AI_OCR_MAX_TEXTS 64

struct sc_ai_ocr_text {
    char *text;
    int center_x;
    int center_y;
    float confidence;
};

struct sc_ai_ocr_result {
    struct sc_ai_ocr_text texts[SC_AI_OCR_MAX_TEXTS];
    size_t count;
};

struct sc_ai_ocr {
    sc_pid pid;
    sc_pipe pipe_stdin;
    sc_pipe pipe_stdout;
    bool running;
};

// Start the OCR daemon. Returns true if the daemon started and loaded
// successfully. Returns false if Python or PaddleOCR is unavailable
// (non-fatal — agent works without OCR).
bool
sc_ai_ocr_start(struct sc_ai_ocr *ocr);

// Stop the OCR daemon gracefully.
void
sc_ai_ocr_stop(struct sc_ai_ocr *ocr);

// Send JPEG data to the daemon and receive OCR results.
// Returns true on success. On failure, the result is zeroed.
bool
sc_ai_ocr_process(struct sc_ai_ocr *ocr,
                   const uint8_t *jpeg_data, size_t jpeg_size,
                   struct sc_ai_ocr_result *result);

// Format OCR results as a text prompt string for the LLM.
// Caller must free the returned string.
char *
sc_ai_ocr_format_prompt(const struct sc_ai_ocr_result *result);

// Free resources inside an OCR result.
void
sc_ai_ocr_result_destroy(struct sc_ai_ocr_result *result);

#endif
