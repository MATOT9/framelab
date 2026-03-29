#include <stddef.h>
#include <stdint.h>

#include "framelab_native/decode/mono_packed.h"
#include "framelab_native/decode/packed_bits.h"

FramelabStatus decode_mono12p(const FramelabDecodeParams *params) {
    if (params == NULL || params->src == NULL || params->dst == NULL) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    if (params->width == 0U || params->height == 0U) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    if ((params->width & 1U) != 0U) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    if (params->src_stride_bytes < (params->width / 2U) * 3U) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    if (params->dst_stride_pixels < params->width) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }

    for (uint32_t y = 0U; y < params->height; ++y) {
        const uint8_t *src_row = params->src + (size_t)y * params->src_stride_bytes;
        uint16_t *dst_row = params->dst + (size_t)y * params->dst_stride_pixels;
        uint32_t x = 0U;
        for (uint32_t g = 0U; g < params->width / 2U; ++g) {
            size_t i = (size_t)g * 3U;
            uint8_t b0 = src_row[i];
            uint8_t b1 = src_row[i + 1U];
            uint8_t b2 = src_row[i + 2U];
            dst_row[x++] = framelab_unpack_mono12p_p0(b0, b1);
            dst_row[x++] = framelab_unpack_mono12p_p1(b1, b2);
        }
    }
    return FRAMELAB_STATUS_OK;
}
