#include <math.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

#include "framelab_native/metrics/app_metrics.h"
#include "framelab_native/metrics/stats.h"
#include "framelab_native/common/roi.h"
#include "view_utils.h"

typedef struct FramelabMinHeap {
    double *data;
    uint32_t size;
    uint32_t capacity;
} FramelabMinHeap;

static void heap_swap(double *a, double *b) {
    double tmp = *a;
    *a = *b;
    *b = tmp;
}

static void heap_sift_up(FramelabMinHeap *heap, uint32_t index) {
    while (index > 0U) {
        uint32_t parent = (index - 1U) / 2U;
        if (!(heap->data[index] < heap->data[parent])) {
            break;
        }
        heap_swap(&heap->data[index], &heap->data[parent]);
        index = parent;
    }
}

static void heap_sift_down(FramelabMinHeap *heap, uint32_t index) {
    for (;;) {
        uint32_t left = index * 2U + 1U;
        uint32_t right = left + 1U;
        uint32_t smallest = index;
        if (left < heap->size && heap->data[left] < heap->data[smallest]) {
            smallest = left;
        }
        if (right < heap->size && heap->data[right] < heap->data[smallest]) {
            smallest = right;
        }
        if (smallest == index) {
            break;
        }
        heap_swap(&heap->data[index], &heap->data[smallest]);
        index = smallest;
    }
}

static int heap_push_topk(FramelabMinHeap *heap, double value) {
    if (heap->capacity == 0U) {
        return 1;
    }
    if (heap->size < heap->capacity) {
        heap->data[heap->size] = value;
        heap_sift_up(heap, heap->size);
        heap->size += 1U;
        return 1;
    }
    if (value <= heap->data[0]) {
        return 1;
    }
    heap->data[0] = value;
    heap_sift_down(heap, 0U);
    return 1;
}

static FramelabStatus validate_background_pair(const FramelabImageView *image,
                                              const FramelabImageView *background) {
    FramelabStatus status = framelab_validate_image_view(image);
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }
    if (background == NULL) {
        return FRAMELAB_STATUS_OK;
    }
    status = framelab_validate_image_view(background);
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }
    if (background->width != image->width || background->height != image->height) {
        return FRAMELAB_STATUS_SIZE_MISMATCH;
    }
    return FRAMELAB_STATUS_OK;
}

static void update_integer_semantics(FramelabRunningStats *stats, double value, int floatish) {
    if (floatish) {
        if (!isfinite(value)) {
            return;
        }
        framelab_running_stats_update(stats, value);
        return;
    }
    framelab_running_stats_update(stats, value);
}

FramelabStatus framelab_compute_static_scan(const FramelabStaticScanParams *params,
                                            FramelabStaticScanResult *result) {
    FramelabRunningStats stats;
    int floatish = 0;

    if (params == NULL || result == NULL) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    FramelabStatus status = framelab_validate_image_view(&params->image);
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }

    floatish = framelab_view_is_floatish(&params->image, NULL, FRAMELAB_BG_NONE);
    framelab_running_stats_init(&stats);
    for (uint32_t y = 0U; y < params->image.height; ++y) {
        for (uint32_t x = 0U; x < params->image.width; ++x) {
            update_integer_semantics(&stats, framelab_sample_at(&params->image, x, y), floatish);
        }
    }

    memset(result, 0, sizeof(*result));
    result->pixel_count = (uint64_t)params->image.width * (uint64_t)params->image.height;
    result->nonzero_count = stats.nonzero_count;
    result->min_non_zero = stats.nonzero_count > 0U
        ? framelab_round_clamp_nonnegative_i64(stats.min_nonzero)
        : 0;
    result->max_pixel = stats.count > 0U
        ? framelab_round_clamp_nonnegative_i64(stats.max_value)
        : 0;
    return FRAMELAB_STATUS_OK;
}

FramelabStatus framelab_compute_dynamic_metrics(
    const FramelabDynamicMetricsParams *params,
    FramelabDynamicMetricsResult *result) {
    FramelabRunningStats stats;
    FramelabMinHeap heap;
    FramelabStatus status;
    uint64_t pixel_count;
    int floatish;

    if (params == NULL || result == NULL) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    status = validate_background_pair(&params->image, params->background);
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }

    pixel_count = (uint64_t)params->image.width * (uint64_t)params->image.height;
    heap.data = NULL;
    heap.size = 0U;
    heap.capacity = 0U;
    if (params->use_topk) {
        uint64_t requested = params->topk_count > 0U ? (uint64_t)params->topk_count : 1U;
        uint64_t actual = requested < pixel_count ? requested : pixel_count;
        if (actual > 0U) {
            if (actual > (uint64_t)UINT32_MAX) {
                return FRAMELAB_STATUS_OUT_OF_RANGE;
            }
            heap.capacity = (uint32_t)actual;
            heap.data = (double *)malloc((size_t)heap.capacity * sizeof(double));
            if (heap.data == NULL) {
                return FRAMELAB_STATUS_ALLOC_FAILED;
            }
        }
    }

    floatish = framelab_view_is_floatish(&params->image, params->background, params->background_mode);
    framelab_running_stats_init(&stats);
    memset(result, 0, sizeof(*result));
    result->topk_mean = NAN;
    result->topk_stddev = NAN;
    result->topk_sem = NAN;

    for (uint32_t y = 0U; y < params->image.height; ++y) {
        for (uint32_t x = 0U; x < params->image.width; ++x) {
            double value = framelab_sample_at(&params->image, x, y);
            value = framelab_apply_background_value(
                value,
                params->background,
                x,
                y,
                params->background_mode
            );

            update_integer_semantics(&stats, value, floatish);
            if (params->use_threshold && value >= params->threshold) {
                result->threshold_count += 1U;
            }
            if (heap.capacity > 0U) {
                heap_push_topk(&heap, value);
            }
        }
    }

    result->pixel_count = pixel_count;
    result->nonzero_count = stats.nonzero_count;
    result->min_non_zero = stats.nonzero_count > 0U
        ? framelab_round_clamp_nonnegative_i64(stats.min_nonzero)
        : 0;
    result->max_pixel = stats.count > 0U
        ? framelab_round_clamp_nonnegative_i64(stats.max_value)
        : 0;

    if (heap.capacity > 0U) {
        double mean = 0.0;
        double m2 = 0.0;
        uint32_t count = heap.size;
        for (uint32_t i = 0U; i < count; ++i) {
            double delta = heap.data[i] - mean;
            mean += delta / (double)(i + 1U);
            m2 += delta * (heap.data[i] - mean);
        }
        result->topk_actual_count = count;
        result->topk_mean = mean;
        result->topk_stddev = count > 0U ? sqrt(m2 / (double)count) : NAN;
        result->topk_sem = count > 0U ? result->topk_stddev / sqrt((double)count) : NAN;
    }

    free(heap.data);
    return FRAMELAB_STATUS_OK;
}

FramelabStatus framelab_compute_roi_metrics(const FramelabRoiMetricsParams *params,
                                            FramelabRoiMetricsResult *result) {
    FramelabRunningStats stats;
    FramelabStatus status;

    if (params == NULL || result == NULL) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    status = validate_background_pair(&params->image, params->background);
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }

    memset(result, 0, sizeof(*result));
    result->roi_max = NAN;
    result->roi_mean = NAN;
    result->roi_stddev = NAN;
    result->roi_sem = NAN;

    if (params->roi.x1 <= params->roi.x0 || params->roi.y1 <= params->roi.y0) {
        return FRAMELAB_STATUS_OK;
    }
    if (!framelab_roi_is_valid(&params->roi, params->image.width, params->image.height)) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }

    framelab_running_stats_init(&stats);
    for (int32_t y = params->roi.y0; y < params->roi.y1; ++y) {
        for (int32_t x = params->roi.x0; x < params->roi.x1; ++x) {
            double value = framelab_sample_at(&params->image, (uint32_t)x, (uint32_t)y);
            value = framelab_apply_background_value(
                value,
                params->background,
                (uint32_t)x,
                (uint32_t)y,
                params->background_mode
            );
            framelab_running_stats_update(&stats, value);
        }
    }

    result->roi_count = stats.count;
    if (stats.count == 0U) {
        return FRAMELAB_STATUS_OK;
    }
    result->roi_max = stats.max_value;
    result->roi_mean = stats.mean;
    result->roi_stddev = framelab_running_stats_stddev(&stats);
    result->roi_sem = result->roi_stddev / sqrt((double)stats.count);
    return FRAMELAB_STATUS_OK;
}
