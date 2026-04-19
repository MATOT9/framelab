#ifndef FRAMELAB_NATIVE_METRICS_APP_METRICS_H
#define FRAMELAB_NATIVE_METRICS_APP_METRICS_H

#include <stdint.h>

#include "framelab_native/common/status.h"
#include "framelab_native/common/types.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct FramelabStaticScanParams {
    FramelabImageView image;
} FramelabStaticScanParams;

typedef struct FramelabStaticScanResult {
    uint64_t pixel_count;
    uint64_t nonzero_count;
    int64_t min_non_zero;
    int64_t max_pixel;
} FramelabStaticScanResult;

typedef struct FramelabDynamicMetricsParams {
    FramelabImageView image;
    const FramelabImageView *background;
    FramelabBackgroundMode background_mode;
    int use_threshold;
    double threshold;
    int use_topk;
    uint32_t topk_count;
} FramelabDynamicMetricsParams;

typedef struct FramelabDynamicMetricsResult {
    uint64_t pixel_count;
    uint64_t nonzero_count;
    uint64_t threshold_count;
    int64_t min_non_zero;
    int64_t max_pixel;
    uint32_t topk_actual_count;
    double topk_mean;
    double topk_stddev;
    double topk_sem;
} FramelabDynamicMetricsResult;

typedef struct FramelabRoiMetricsParams {
    FramelabImageView image;
    const FramelabImageView *background;
    FramelabBackgroundMode background_mode;
    FramelabRoi roi;
    int use_topk;
    uint32_t topk_count;
} FramelabRoiMetricsParams;

typedef struct FramelabRoiMetricsResult {
    uint64_t roi_count;
    double roi_max;
    double roi_sum;
    double roi_mean;
    double roi_stddev;
    double roi_sem;
    uint32_t roi_topk_actual_count;
    double roi_topk_mean;
    double roi_topk_stddev;
    double roi_topk_sem;
} FramelabRoiMetricsResult;

typedef struct FramelabRawStaticScanParams {
    FramelabRawLoadParams raw;
    FramelabRawExecutionInfo *execution_info;
} FramelabRawStaticScanParams;

typedef struct FramelabRawDynamicMetricsParams {
    FramelabRawLoadParams raw;
    FramelabRawExecutionInfo *execution_info;
    const FramelabImageView *background;
    FramelabBackgroundMode background_mode;
    int use_threshold;
    double threshold;
    int use_topk;
    uint32_t topk_count;
} FramelabRawDynamicMetricsParams;

FramelabStatus framelab_compute_static_scan(const FramelabStaticScanParams *params,
                                            FramelabStaticScanResult *result);

FramelabStatus framelab_compute_raw_static_scan(
    const FramelabRawStaticScanParams *params,
    FramelabStaticScanResult *result);

FramelabStatus framelab_compute_dynamic_metrics(
    const FramelabDynamicMetricsParams *params,
    FramelabDynamicMetricsResult *result);

FramelabStatus framelab_compute_raw_dynamic_metrics(
    const FramelabRawDynamicMetricsParams *params,
    FramelabDynamicMetricsResult *result);

FramelabStatus framelab_compute_roi_metrics(const FramelabRoiMetricsParams *params,
                                            FramelabRoiMetricsResult *result);

#ifdef __cplusplus
}
#endif

#endif
