#include <stddef.h>

#include "framelab_native/metrics/roi_stats.h"
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

FramelabStatus framelab_compute_roi_stats(const FramelabImageView *image,
                                          const FramelabRoi *roi,
                                          double *out_mean,
                                          double *out_stddev,
                                          uint64_t *out_count) {
    FramelabRunningStats stats;
    if (image == NULL || roi == NULL || out_mean == NULL || out_stddev == NULL || out_count == NULL) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    if (!framelab_roi_is_valid(roi, image->width, image->height)) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }

    framelab_running_stats_init(&stats);
    for (int32_t y = roi->y0; y < roi->y1; ++y) {
        for (int32_t x = roi->x0; x < roi->x1; ++x) {
            framelab_running_stats_update(&stats, sample_at(image, (uint32_t)x, (uint32_t)y));
        }
    }

    *out_mean = stats.count > 0U ? stats.mean : 0.0;
    *out_stddev = framelab_running_stats_stddev(&stats);
    *out_count = stats.count;
    return FRAMELAB_STATUS_OK;
}
