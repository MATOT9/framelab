#include <math.h>
#include <stddef.h>
#include <string.h>

#include "framelab_native/metrics/metrics.h"
#include "framelab_native/metrics/stats.h"
#include "framelab_native/common/roi.h"

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

static FramelabStatus validate_image_view(const FramelabImageView *view) {
    if (view == NULL || view->data == NULL || view->width == 0U || view->height == 0U) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    switch (view->sample_type) {
        case FRAMELAB_SAMPLE_U8:
            if (view->stride_bytes < view->width) return FRAMELAB_STATUS_INVALID_ARGUMENT;
            return FRAMELAB_STATUS_OK;
        case FRAMELAB_SAMPLE_U16:
            if (view->stride_bytes < view->width * sizeof(uint16_t)) return FRAMELAB_STATUS_INVALID_ARGUMENT;
            return FRAMELAB_STATUS_OK;
        case FRAMELAB_SAMPLE_F32:
            if (view->stride_bytes < view->width * sizeof(float)) return FRAMELAB_STATUS_INVALID_ARGUMENT;
            return FRAMELAB_STATUS_OK;
        case FRAMELAB_SAMPLE_F64:
            if (view->stride_bytes < view->width * sizeof(double)) return FRAMELAB_STATUS_INVALID_ARGUMENT;
            return FRAMELAB_STATUS_OK;
        default:
            return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
}

static double apply_background_mode(double value, double bg, FramelabBackgroundMode mode) {
    if (mode == FRAMELAB_BG_NONE) {
        return value;
    }
    value -= bg;
    if (mode == FRAMELAB_BG_SUBTRACT_CLAMP_ZERO && value < 0.0) {
        return 0.0;
    }
    return value;
}

FramelabStatus framelab_compute_metrics(
    const FramelabMetricsParams *params,
    FramelabMetricsResult *result
) {
    FramelabRunningStats global_stats;
    FramelabRunningStats roi_stats;

    if (params == NULL || result == NULL) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    FramelabStatus status = validate_image_view(&params->image);
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }
    if (params->background != NULL) {
        status = validate_image_view(params->background);
        if (status != FRAMELAB_STATUS_OK) {
            return status;
        }
        if (params->background->width != params->image.width ||
            params->background->height != params->image.height) {
            return FRAMELAB_STATUS_SIZE_MISMATCH;
        }
    }
    if (!framelab_roi_is_valid(params->roi, params->image.width, params->image.height)) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    if (params->use_histogram) {
        if (params->histogram_bins == NULL || params->histogram_bin_count == 0U) {
            return FRAMELAB_STATUS_INVALID_ARGUMENT;
        }
        if (!(params->histogram_max > params->histogram_min)) {
            return FRAMELAB_STATUS_INVALID_ARGUMENT;
        }
        memset(params->histogram_bins, 0, (size_t)params->histogram_bin_count * sizeof(uint64_t));
    }

    framelab_running_stats_init(&global_stats);
    framelab_running_stats_init(&roi_stats);
    result->threshold_count = 0U;

    const double hist_scale = params->use_histogram
        ? (double)params->histogram_bin_count / (params->histogram_max - params->histogram_min)
        : 0.0;

    for (uint32_t y = 0U; y < params->image.height; ++y) {
        for (uint32_t x = 0U; x < params->image.width; ++x) {
            double value = sample_at(&params->image, x, y);
            if (params->background != NULL && params->background_mode != FRAMELAB_BG_NONE) {
                double bg = sample_at(params->background, x, y);
                value = apply_background_mode(value, bg, params->background_mode);
            }

            framelab_running_stats_update(&global_stats, value);
            if (params->use_threshold && value >= params->threshold) {
                result->threshold_count += 1U;
            }
            if (params->use_histogram && value >= params->histogram_min && value <= params->histogram_max) {
                uint32_t bin = (uint32_t)((value - params->histogram_min) * hist_scale);
                if (bin >= params->histogram_bin_count) {
                    bin = params->histogram_bin_count - 1U;
                }
                params->histogram_bins[bin] += 1U;
            }
            if (framelab_roi_contains(params->roi, (int32_t)x, (int32_t)y)) {
                framelab_running_stats_update(&roi_stats, value);
            }
        }
    }

    memset(result, 0, sizeof(*result));
    result->pixel_count = global_stats.count;
    result->nonzero_count = global_stats.nonzero_count;
    result->threshold_count = params->use_threshold ? result->threshold_count : 0U;
    result->min_value = global_stats.count > 0U ? global_stats.min_value : 0.0;
    result->max_value = global_stats.count > 0U ? global_stats.max_value : 0.0;
    result->min_nonzero = global_stats.nonzero_count > 0U ? global_stats.min_nonzero : 0.0;
    result->sum = global_stats.sum;
    result->mean = global_stats.count > 0U ? global_stats.mean : 0.0;
    result->stddev = framelab_running_stats_stddev(&global_stats);
    result->roi_count = roi_stats.count;
    result->roi_sum = roi_stats.sum;
    result->roi_mean = roi_stats.count > 0U ? roi_stats.mean : 0.0;
    result->roi_stddev = framelab_running_stats_stddev(&roi_stats);
    return FRAMELAB_STATUS_OK;
}
