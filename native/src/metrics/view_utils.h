#ifndef FRAMELAB_NATIVE_METRICS_VIEW_UTILS_H
#define FRAMELAB_NATIVE_METRICS_VIEW_UTILS_H

#include <limits.h>
#include <math.h>
#include <stddef.h>
#include <stdint.h>

#include "framelab_native/common/status.h"
#include "framelab_native/common/types.h"

static inline double framelab_sample_at(const FramelabImageView *view, uint32_t x, uint32_t y) {
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

static inline FramelabStatus framelab_validate_image_view(const FramelabImageView *view) {
    if (view == NULL || view->data == NULL || view->width == 0U || view->height == 0U) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    switch (view->sample_type) {
        case FRAMELAB_SAMPLE_U8:
            return view->stride_bytes >= view->width
                ? FRAMELAB_STATUS_OK
                : FRAMELAB_STATUS_INVALID_ARGUMENT;
        case FRAMELAB_SAMPLE_U16:
            return view->stride_bytes >= view->width * sizeof(uint16_t)
                ? FRAMELAB_STATUS_OK
                : FRAMELAB_STATUS_INVALID_ARGUMENT;
        case FRAMELAB_SAMPLE_F32:
            return view->stride_bytes >= view->width * sizeof(float)
                ? FRAMELAB_STATUS_OK
                : FRAMELAB_STATUS_INVALID_ARGUMENT;
        case FRAMELAB_SAMPLE_F64:
            return view->stride_bytes >= view->width * sizeof(double)
                ? FRAMELAB_STATUS_OK
                : FRAMELAB_STATUS_INVALID_ARGUMENT;
        default:
            return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
}

static inline int framelab_view_is_floatish(const FramelabImageView *view,
                                            const FramelabImageView *background,
                                            FramelabBackgroundMode background_mode) {
    if (view->sample_type == FRAMELAB_SAMPLE_F32 || view->sample_type == FRAMELAB_SAMPLE_F64) {
        return 1;
    }
    if (background != NULL && background_mode != FRAMELAB_BG_NONE) {
        return 1;
    }
    return 0;
}

static inline double framelab_apply_background_value(double value,
                                                     const FramelabImageView *background,
                                                     uint32_t x,
                                                     uint32_t y,
                                                     FramelabBackgroundMode mode) {
    if (background == NULL || mode == FRAMELAB_BG_NONE) {
        return value;
    }
    value -= framelab_sample_at(background, x, y);
    if (mode == FRAMELAB_BG_SUBTRACT_CLAMP_ZERO && value < 0.0) {
        value = 0.0;
    }
    return value;
}

static inline int64_t framelab_round_clamp_nonnegative_i64(double value) {
    if (!isfinite(value)) {
        return 0;
    }
    if (value <= 0.0) {
        return 0;
    }
    if (value >= (double)LLONG_MAX) {
        return LLONG_MAX;
    }
    return (int64_t)llround(value);
}

#endif
