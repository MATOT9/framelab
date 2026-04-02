#ifndef FRAMELAB_NATIVE_COMMON_TYPES_H
#define FRAMELAB_NATIVE_COMMON_TYPES_H

#include <stddef.h>
#include <stdint.h>

#include "framelab_native/common/pixel_formats.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum FramelabSampleType {
    FRAMELAB_SAMPLE_U8 = 1,
    FRAMELAB_SAMPLE_U16,
    FRAMELAB_SAMPLE_F32,
    FRAMELAB_SAMPLE_F64
} FramelabSampleType;

typedef struct FramelabImageView {
    const void *data;
    uint32_t width;
    uint32_t height;
    uint32_t stride_bytes;
    FramelabSampleType sample_type;
} FramelabImageView;

typedef struct FramelabMutableImageView {
    void *data;
    uint32_t width;
    uint32_t height;
    uint32_t stride_bytes;
    FramelabSampleType sample_type;
} FramelabMutableImageView;

typedef struct FramelabRoi {
    int32_t x0;
    int32_t y0;
    int32_t x1;
    int32_t y1;
} FramelabRoi;

typedef struct FramelabDecodeParams {
    const uint8_t *src;
    size_t src_size;
    uint32_t width;
    uint32_t height;
    uint32_t src_stride_bytes;
    FramelabPixelFormat pixel_format;
    uint16_t *dst;
    uint32_t dst_stride_pixels;
    int simd_enabled;
} FramelabDecodeParams;

typedef enum FramelabRawIoMode {
    FRAMELAB_RAW_IO_AUTO = 0,
    FRAMELAB_RAW_IO_BUFFERED_ONLY,
    FRAMELAB_RAW_IO_MMAP_ONLY
} FramelabRawIoMode;

typedef enum FramelabSimdIsa {
    FRAMELAB_SIMD_SCALAR = 0,
    FRAMELAB_SIMD_SSE2,
    FRAMELAB_SIMD_NEON
} FramelabSimdIsa;

typedef struct FramelabRawExecutionInfo {
    int used_mmap;
    FramelabSimdIsa simd_isa;
} FramelabRawExecutionInfo;

typedef struct FramelabRawLoadParams {
    const char *path;
    uint32_t width;
    uint32_t height;
    uint32_t src_stride_bytes;
    size_t offset_bytes;
    FramelabPixelFormat pixel_format;
    FramelabRawIoMode io_mode;
    int simd_enabled;
} FramelabRawLoadParams;

typedef enum FramelabBackgroundMode {
    FRAMELAB_BG_NONE = 0,
    FRAMELAB_BG_SUBTRACT,
    FRAMELAB_BG_SUBTRACT_CLAMP_ZERO
} FramelabBackgroundMode;

typedef struct FramelabMetricsParams {
    FramelabImageView image;
    const FramelabImageView *background;
    FramelabBackgroundMode background_mode;
    const FramelabRoi *roi;
    int use_threshold;
    double threshold;
    int use_histogram;
    double histogram_min;
    double histogram_max;
    uint32_t histogram_bin_count;
    uint64_t *histogram_bins;
} FramelabMetricsParams;

typedef struct FramelabMetricsResult {
    uint64_t pixel_count;
    uint64_t nonzero_count;
    uint64_t threshold_count;
    double min_value;
    double max_value;
    double min_nonzero;
    double sum;
    double mean;
    double stddev;
    uint64_t roi_count;
    double roi_sum;
    double roi_mean;
    double roi_stddev;
} FramelabMetricsResult;

#ifdef __cplusplus
}
#endif

#endif
