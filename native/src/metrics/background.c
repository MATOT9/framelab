#include <stddef.h>

#include "framelab_native/metrics/background.h"

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

FramelabStatus framelab_apply_background_to_f32(const FramelabImageView *image,
                                                const FramelabImageView *background,
                                                FramelabBackgroundMode mode,
                                                float *dst,
                                                uint32_t dst_stride_floats) {
    if (image == NULL || background == NULL || dst == NULL) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    if (image->width != background->width || image->height != background->height) {
        return FRAMELAB_STATUS_SIZE_MISMATCH;
    }
    if (dst_stride_floats < image->width) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }

    for (uint32_t y = 0U; y < image->height; ++y) {
        float *dst_row = dst + (size_t)y * dst_stride_floats;
        for (uint32_t x = 0U; x < image->width; ++x) {
            double value = sample_at(image, x, y) - sample_at(background, x, y);
            if (mode == FRAMELAB_BG_SUBTRACT_CLAMP_ZERO && value < 0.0) {
                value = 0.0;
            }
            dst_row[x] = (float)value;
        }
    }
    return FRAMELAB_STATUS_OK;
}
