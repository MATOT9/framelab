#include <string.h>

#include "framelab_native/common/simd.h"
#include "framelab_native/loaders/raw_loader.h"
#include "framelab_native/loaders/raw_source.h"
#include "framelab_native/decode/decode.h"

FramelabStatus framelab_load_raw_and_decode(
    const FramelabRawLoadParams *params,
    uint16_t *dst,
    uint32_t dst_stride_pixels
) {
    return framelab_load_raw_and_decode_with_info(params, dst, dst_stride_pixels, NULL);
}

FramelabStatus framelab_load_raw_and_decode_with_info(
    const FramelabRawLoadParams *params,
    uint16_t *dst,
    uint32_t dst_stride_pixels,
    FramelabRawExecutionInfo *execution_info) {
    FramelabRawSource source;
    FramelabDecodeParams decode_params;
    FramelabStatus status;

    if (params == NULL || params->path == NULL || dst == NULL) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    if (params->width == 0U || params->height == 0U || dst_stride_pixels < params->width) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }

    status = framelab_raw_source_open(params, &source);
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }

    memset(&decode_params, 0, sizeof(decode_params));
    decode_params.src = source.data + params->offset_bytes;
    decode_params.src_size = source.size - params->offset_bytes;
    decode_params.width = params->width;
    decode_params.height = params->height;
    decode_params.src_stride_bytes = source.src_stride_bytes;
    decode_params.pixel_format = params->pixel_format;
    decode_params.dst = dst;
    decode_params.dst_stride_pixels = dst_stride_pixels;
    decode_params.simd_enabled = params->simd_enabled;
    status = framelab_decode(&decode_params);

    if (execution_info != NULL) {
        execution_info->used_mmap = source.used_mmap;
        execution_info->simd_isa = framelab_resolve_decode_simd_isa(
            params->pixel_format,
            params->simd_enabled);
    }
    framelab_raw_source_close(&source);
    return status;
}
