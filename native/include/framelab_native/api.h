#ifndef FRAMELAB_NATIVE_API_H
#define FRAMELAB_NATIVE_API_H

#include "framelab_native/common/status.h"
#include "framelab_native/common/types.h"
#include "framelab_native/metrics/app_metrics.h"

#ifdef __cplusplus
extern "C" {
#endif

FramelabStatus framelab_decode(const FramelabDecodeParams *params);
FramelabStatus framelab_load_raw_and_decode(const FramelabRawLoadParams *params,
                                            uint16_t *dst,
                                            uint32_t dst_stride_pixels);
FramelabStatus framelab_load_raw_and_decode_with_info(
    const FramelabRawLoadParams *params,
    uint16_t *dst,
    uint32_t dst_stride_pixels,
    FramelabRawExecutionInfo *execution_info);
FramelabStatus framelab_compute_metrics(const FramelabMetricsParams *params,
                                        FramelabMetricsResult *result);
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
FramelabStatus framelab_apply_background_to_f32(const FramelabImageView *image,
                                                const FramelabImageView *background,
                                                FramelabBackgroundMode mode,
                                                float *dst,
                                                uint32_t dst_stride_floats);
FramelabStatus framelab_compute_roi_stats(const FramelabImageView *image,
                                          const FramelabRoi *roi,
                                          double *out_mean,
                                          double *out_stddev,
                                          uint64_t *out_count);
FramelabStatus framelab_compute_histogram(const FramelabImageView *image,
                                          double value_min,
                                          double value_max,
                                          uint32_t bin_count,
                                          uint64_t *bins);

#ifdef __cplusplus
}
#endif

#endif
