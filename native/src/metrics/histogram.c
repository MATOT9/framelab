#include <stddef.h>
#include <string.h>

#include "framelab_native/metrics/histogram.h"

static double sample_at(const FramelabImageView *view, uint32_t x, uint32_t y) {
    const uint8_t *row = (const uint8_t *)view->data + (size_t)y * view->stride_bytes;
    switch (view->sample_type) {
        case FRAMELAB_SAMPLE_U8:
            return ((const uint8_t *)row)[x];
        case FRAMELAB_SAMPLE_U16:
            return ((const uint16_t *)row)[x];
        case FRAMELAB_SAMPLE_F32:
            return ((const float *)row)[x];
        case FRAMELAB_SAMPLE_F64:
            return ((const double *)row)[x];
        default:
            return 0.0;
    }
}

FramelabStatus framelab_compute_histogram(
    const FramelabImageView *image,
    double value_min,
    double value_max,
    uint32_t bin_count,
    uint64_t *bins
) {
    if (image == NULL || bins == NULL || bin_count == 0U) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    if (!(value_max > value_min)) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }

    memset(bins, 0, (size_t)bin_count * sizeof(uint64_t));
    const double scale = (double)bin_count / (value_max - value_min);
    for (uint32_t y = 0U; y < image->height; ++y) {
        for (uint32_t x = 0U; x < image->width; ++x) {
            double value = sample_at(image, x, y);
            if (value >= value_min && value <= value_max) {
                uint32_t bin = (uint32_t)((value - value_min) * scale);
                if (bin >= bin_count) {
                    bin = bin_count - 1U;
                }
                bins[bin] += 1U;
            }
        }
    }
    return FRAMELAB_STATUS_OK;
}
