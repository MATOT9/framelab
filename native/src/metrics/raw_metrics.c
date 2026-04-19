#include <math.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

#include "framelab_native/decode/decode.h"
#include "framelab_native/loaders/raw_source.h"
#include "framelab_native/metrics/app_metrics.h"
#include "framelab_native/metrics/stats.h"
#include "framelab_native/common/simd.h"
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

static FramelabStatus validate_background_for_raw(
    uint32_t width,
    uint32_t height,
    const FramelabImageView *background
) {
    if (background == NULL) {
        return FRAMELAB_STATUS_OK;
    }
    if (framelab_validate_image_view(background) != FRAMELAB_STATUS_OK) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    if (background->width != width || background->height != height) {
        return FRAMELAB_STATUS_SIZE_MISMATCH;
    }
    return FRAMELAB_STATUS_OK;
}

static FramelabStatus decode_raw_row(
    const FramelabRawSource *source,
    const FramelabRawLoadParams *raw,
    uint32_t row_index,
    uint16_t *scratch_row
) {
    FramelabDecodeParams params;
    const uint8_t *src_row = source->data + raw->offset_bytes + (size_t)row_index * source->src_stride_bytes;

    memset(&params, 0, sizeof(params));
    params.src = src_row;
    params.src_size = source->size - raw->offset_bytes - (size_t)row_index * source->src_stride_bytes;
    params.width = raw->width;
    params.height = 1U;
    params.src_stride_bytes = source->src_stride_bytes;
    params.pixel_format = raw->pixel_format;
    params.dst = scratch_row;
    params.dst_stride_pixels = raw->width;
    params.simd_enabled = raw->simd_enabled;
    return framelab_decode(&params);
}

FramelabStatus framelab_compute_raw_static_scan(
    const FramelabRawStaticScanParams *params,
    FramelabStaticScanResult *result) {
    FramelabRawSource source;
    uint16_t *scratch_row = NULL;
    uint64_t pixel_count;
    uint64_t nonzero_count = 0U;
    int64_t min_non_zero = 0;
    int64_t max_pixel = 0;
    FramelabStatus status;

    if (params == NULL || result == NULL) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    memset(result, 0, sizeof(*result));
    status = framelab_raw_source_open(&params->raw, &source);
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }
    if (params->execution_info != NULL) {
        params->execution_info->used_mmap = source.used_mmap;
        params->execution_info->simd_isa = framelab_resolve_decode_simd_isa(
            params->raw.pixel_format,
            params->raw.simd_enabled);
    }
    scratch_row = (uint16_t *)malloc((size_t)params->raw.width * sizeof(uint16_t));
    if (scratch_row == NULL) {
        framelab_raw_source_close(&source);
        return FRAMELAB_STATUS_ALLOC_FAILED;
    }

    for (uint32_t y = 0U; y < params->raw.height; ++y) {
        status = decode_raw_row(&source, &params->raw, y, scratch_row);
        if (status != FRAMELAB_STATUS_OK) {
            free(scratch_row);
            framelab_raw_source_close(&source);
            return status;
        }
        for (uint32_t x = 0U; x < params->raw.width; ++x) {
            int64_t value = scratch_row[x];
            if (value > max_pixel) {
                max_pixel = value;
            }
            if (value > 0 && (nonzero_count == 0U || value < min_non_zero)) {
                min_non_zero = value;
            }
            if (value > 0) {
                nonzero_count += 1U;
            }
        }
    }

    pixel_count = (uint64_t)params->raw.width * (uint64_t)params->raw.height;
    result->pixel_count = pixel_count;
    result->nonzero_count = nonzero_count;
    result->min_non_zero = nonzero_count > 0U ? min_non_zero : 0;
    result->max_pixel = max_pixel;

    free(scratch_row);
    framelab_raw_source_close(&source);
    return FRAMELAB_STATUS_OK;
}

FramelabStatus framelab_compute_raw_dynamic_metrics(
    const FramelabRawDynamicMetricsParams *params,
    FramelabDynamicMetricsResult *result) {
    FramelabRawSource source;
    FramelabMinHeap heap;
    uint16_t *scratch_row = NULL;
    FramelabRunningStats stats;
    uint64_t pixel_count;
    FramelabStatus status;
    int floatish;

    if (params == NULL || result == NULL) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    status = validate_background_for_raw(
        params->raw.width,
        params->raw.height,
        params->background);
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }
    memset(result, 0, sizeof(*result));
    result->topk_mean = NAN;
    result->topk_stddev = NAN;
    result->topk_sem = NAN;

    pixel_count = (uint64_t)params->raw.width * (uint64_t)params->raw.height;
    heap.data = NULL;
    heap.size = 0U;
    heap.capacity = 0U;
    if (params->use_topk) {
        uint64_t requested = params->topk_count > 0U ? (uint64_t)params->topk_count : 1U;
        uint64_t actual = requested < pixel_count ? requested : pixel_count;
        if (actual > (uint64_t)UINT32_MAX) {
            return FRAMELAB_STATUS_OUT_OF_RANGE;
        }
        if (actual > 0U) {
            heap.capacity = (uint32_t)actual;
            heap.data = (double *)malloc((size_t)heap.capacity * sizeof(double));
            if (heap.data == NULL) {
                return FRAMELAB_STATUS_ALLOC_FAILED;
            }
        }
    }

    status = framelab_raw_source_open(&params->raw, &source);
    if (status != FRAMELAB_STATUS_OK) {
        free(heap.data);
        return status;
    }
    if (params->execution_info != NULL) {
        params->execution_info->used_mmap = source.used_mmap;
        params->execution_info->simd_isa = framelab_resolve_decode_simd_isa(
            params->raw.pixel_format,
            params->raw.simd_enabled);
    }
    scratch_row = (uint16_t *)malloc((size_t)params->raw.width * sizeof(uint16_t));
    if (scratch_row == NULL) {
        framelab_raw_source_close(&source);
        free(heap.data);
        return FRAMELAB_STATUS_ALLOC_FAILED;
    }

    floatish = params->background != NULL && params->background_mode != FRAMELAB_BG_NONE;
    framelab_running_stats_init(&stats);
    for (uint32_t y = 0U; y < params->raw.height; ++y) {
        status = decode_raw_row(&source, &params->raw, y, scratch_row);
        if (status != FRAMELAB_STATUS_OK) {
            free(scratch_row);
            framelab_raw_source_close(&source);
            free(heap.data);
            return status;
        }
        for (uint32_t x = 0U; x < params->raw.width; ++x) {
            double value = scratch_row[x];
            value = framelab_apply_background_value(
                value,
                params->background,
                x,
                y,
                params->background_mode);
            if (floatish) {
                if (isfinite(value)) {
                    framelab_running_stats_update(&stats, value);
                }
            } else {
                framelab_running_stats_update(&stats, value);
            }
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

    free(scratch_row);
    framelab_raw_source_close(&source);
    free(heap.data);
    return FRAMELAB_STATUS_OK;
}
