#include <stddef.h>
#include <stdint.h>
#include <limits.h>

#include "framelab_native/decode/mono_packed.h"
#include "framelab_native/decode/packed_bits.h"

static uint32_t stride_bytes_for_bit_depth(uint32_t width, uint32_t bits_per_pixel) {
    uint64_t total_bits = (uint64_t)width * (uint64_t)bits_per_pixel;
    uint64_t total_bytes = (total_bits + 7U) / 8U;
    if (total_bytes > UINT32_MAX) {
        return 0U;
    }
    return (uint32_t)total_bytes;
}

static FramelabStatus validate_packed_params(
    const FramelabDecodeParams *params,
    uint32_t min_stride_bytes
) {
    if (params == NULL || params->src == NULL || params->dst == NULL) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    if (params->width == 0U || params->height == 0U) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    if (params->src_stride_bytes < min_stride_bytes) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    if (params->dst_stride_pixels < params->width) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    return FRAMELAB_STATUS_OK;
}

static uint8_t row_byte_or_zero(
    const uint8_t *row,
    uint32_t row_bytes,
    size_t index
) {
    return index < (size_t)row_bytes ? row[index] : 0U;
}

FramelabStatus decode_mono10p(const FramelabDecodeParams *params) {
    FramelabStatus status = validate_packed_params(
        params,
        stride_bytes_for_bit_depth(params->width, 10U)
    );
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }

    for (uint32_t y = 0U; y < params->height; ++y) {
        const uint8_t *src_row = params->src + (size_t)y * params->src_stride_bytes;
        uint16_t *dst_row = params->dst + (size_t)y * params->dst_stride_pixels;
        uint32_t x = 0U;
        size_t i = 0U;
        for (; x + 3U < params->width; x += 4U, i += 5U) {
            uint8_t b0 = src_row[i];
            uint8_t b1 = src_row[i + 1U];
            uint8_t b2 = src_row[i + 2U];
            uint8_t b3 = src_row[i + 3U];
            uint8_t b4 = src_row[i + 4U];
            dst_row[x] = framelab_unpack_mono10p_p0(b0, b1);
            dst_row[x + 1U] = framelab_unpack_mono10p_p1(b1, b2);
            dst_row[x + 2U] = framelab_unpack_mono10p_p2(b2, b3);
            dst_row[x + 3U] = framelab_unpack_mono10p_p3(b3, b4);
        }
        if (x < params->width) {
            uint8_t b0 = row_byte_or_zero(src_row, params->src_stride_bytes, i);
            uint8_t b1 = row_byte_or_zero(src_row, params->src_stride_bytes, i + 1U);
            uint8_t b2 = row_byte_or_zero(src_row, params->src_stride_bytes, i + 2U);
            uint8_t b3 = row_byte_or_zero(src_row, params->src_stride_bytes, i + 3U);
            uint8_t b4 = row_byte_or_zero(src_row, params->src_stride_bytes, i + 4U);
            dst_row[x++] = framelab_unpack_mono10p_p0(b0, b1);
            if (x < params->width) {
                dst_row[x++] = framelab_unpack_mono10p_p1(b1, b2);
            }
            if (x < params->width) {
                dst_row[x++] = framelab_unpack_mono10p_p2(b2, b3);
            }
            if (x < params->width) {
                dst_row[x++] = framelab_unpack_mono10p_p3(b3, b4);
            }
        }
    }
    return FRAMELAB_STATUS_OK;
}

FramelabStatus decode_mono10packed(const FramelabDecodeParams *params) {
    FramelabStatus status = validate_packed_params(
        params,
        stride_bytes_for_bit_depth(params->width, 10U)
    );
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }

    for (uint32_t y = 0U; y < params->height; ++y) {
        const uint8_t *src_row = params->src + (size_t)y * params->src_stride_bytes;
        uint16_t *dst_row = params->dst + (size_t)y * params->dst_stride_pixels;
        uint32_t x = 0U;
        size_t i = 0U;
        for (; x + 1U < params->width; x += 2U, i += 3U) {
            uint8_t b0 = src_row[i];
            uint8_t b1 = src_row[i + 1U];
            uint8_t b2 = src_row[i + 2U];
            dst_row[x] = framelab_unpack_mono10packed_p0(b0, b1);
            dst_row[x + 1U] = framelab_unpack_mono10packed_p1(b1, b2);
        }
        if (x < params->width) {
            uint8_t b0 = row_byte_or_zero(src_row, params->src_stride_bytes, i);
            uint8_t b1 = row_byte_or_zero(src_row, params->src_stride_bytes, i + 1U);
            dst_row[x] = framelab_unpack_mono10packed_p0(b0, b1);
        }
    }
    return FRAMELAB_STATUS_OK;
}

FramelabStatus decode_mono12p(const FramelabDecodeParams *params) {
    FramelabStatus status = validate_packed_params(
        params,
        stride_bytes_for_bit_depth(params->width, 12U)
    );
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }

    for (uint32_t y = 0U; y < params->height; ++y) {
        const uint8_t *src_row = params->src + (size_t)y * params->src_stride_bytes;
        uint16_t *dst_row = params->dst + (size_t)y * params->dst_stride_pixels;
        uint32_t x = 0U;
        size_t i = 0U;
        for (; x + 1U < params->width; x += 2U, i += 3U) {
            uint8_t b0 = src_row[i];
            uint8_t b1 = src_row[i + 1U];
            uint8_t b2 = src_row[i + 2U];
            dst_row[x] = framelab_unpack_mono12p_p0(b0, b1);
            dst_row[x + 1U] = framelab_unpack_mono12p_p1(b1, b2);
        }
        if (x < params->width) {
            uint8_t b0 = row_byte_or_zero(src_row, params->src_stride_bytes, i);
            uint8_t b1 = row_byte_or_zero(src_row, params->src_stride_bytes, i + 1U);
            dst_row[x] = framelab_unpack_mono12p_p0(b0, b1);
        }
    }
    return FRAMELAB_STATUS_OK;
}

FramelabStatus decode_mono12packed(const FramelabDecodeParams *params) {
    FramelabStatus status = validate_packed_params(
        params,
        stride_bytes_for_bit_depth(params->width, 12U)
    );
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }

    for (uint32_t y = 0U; y < params->height; ++y) {
        const uint8_t *src_row = params->src + (size_t)y * params->src_stride_bytes;
        uint16_t *dst_row = params->dst + (size_t)y * params->dst_stride_pixels;
        uint32_t x = 0U;
        size_t i = 0U;
        for (; x + 1U < params->width; x += 2U, i += 3U) {
            uint8_t b0 = src_row[i];
            uint8_t b1 = src_row[i + 1U];
            uint8_t b2 = src_row[i + 2U];
            dst_row[x] = framelab_unpack_mono12packed_p0(b0, b1);
            dst_row[x + 1U] = framelab_unpack_mono12packed_p1(b1, b2);
        }
        if (x < params->width) {
            uint8_t b0 = row_byte_or_zero(src_row, params->src_stride_bytes, i);
            uint8_t b1 = row_byte_or_zero(src_row, params->src_stride_bytes, i + 1U);
            dst_row[x] = framelab_unpack_mono12packed_p0(b0, b1);
        }
    }
    return FRAMELAB_STATUS_OK;
}
