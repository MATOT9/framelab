#include <stddef.h>
#include <stdint.h>

#include "framelab_native/decode/mono_unpacked.h"

static FramelabStatus validate_params(const FramelabDecodeParams *params, uint32_t min_stride_bytes) {
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

FramelabStatus decode_mono8(const FramelabDecodeParams *params) {
    FramelabStatus status = validate_params(params, params->width);
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }

    for (uint32_t y = 0U; y < params->height; ++y) {
        const uint8_t *src_row = params->src + (size_t)y * params->src_stride_bytes;
        uint16_t *dst_row = params->dst + (size_t)y * params->dst_stride_pixels;
        for (uint32_t x = 0U; x < params->width; ++x) {
            dst_row[x] = src_row[x];
        }
    }
    return FRAMELAB_STATUS_OK;
}

FramelabStatus decode_mono10_lsb(const FramelabDecodeParams *params) {
    FramelabStatus status = validate_params(params, params->width * 2U);
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }

    for (uint32_t y = 0U; y < params->height; ++y) {
        const uint8_t *src_row = params->src + (size_t)y * params->src_stride_bytes;
        uint16_t *dst_row = params->dst + (size_t)y * params->dst_stride_pixels;
        for (uint32_t x = 0U; x < params->width; ++x) {
            size_t i = (size_t)x * 2U;
            uint16_t word = (uint16_t)src_row[i] | ((uint16_t)src_row[i + 1U] << 8);
            dst_row[x] = (uint16_t)(word & 0x03FFu);
        }
    }
    return FRAMELAB_STATUS_OK;
}

FramelabStatus decode_mono10_msb(const FramelabDecodeParams *params) {
    FramelabStatus status = validate_params(params, params->width * 2U);
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }

    for (uint32_t y = 0U; y < params->height; ++y) {
        const uint8_t *src_row = params->src + (size_t)y * params->src_stride_bytes;
        uint16_t *dst_row = params->dst + (size_t)y * params->dst_stride_pixels;
        for (uint32_t x = 0U; x < params->width; ++x) {
            size_t i = (size_t)x * 2U;
            uint16_t word = (uint16_t)src_row[i] | ((uint16_t)src_row[i + 1U] << 8);
            dst_row[x] = (uint16_t)(word >> 6);
        }
    }
    return FRAMELAB_STATUS_OK;
}

FramelabStatus decode_mono12_lsb(const FramelabDecodeParams *params) {
    FramelabStatus status = validate_params(params, params->width * 2U);
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }

    for (uint32_t y = 0U; y < params->height; ++y) {
        const uint8_t *src_row = params->src + (size_t)y * params->src_stride_bytes;
        uint16_t *dst_row = params->dst + (size_t)y * params->dst_stride_pixels;
        for (uint32_t x = 0U; x < params->width; ++x) {
            size_t i = (size_t)x * 2U;
            uint16_t word = (uint16_t)src_row[i] | ((uint16_t)src_row[i + 1U] << 8);
            dst_row[x] = (uint16_t)(word & 0x0FFFu);
        }
    }
    return FRAMELAB_STATUS_OK;
}

FramelabStatus decode_mono12_msb(const FramelabDecodeParams *params) {
    FramelabStatus status = validate_params(params, params->width * 2U);
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }

    for (uint32_t y = 0U; y < params->height; ++y) {
        const uint8_t *src_row = params->src + (size_t)y * params->src_stride_bytes;
        uint16_t *dst_row = params->dst + (size_t)y * params->dst_stride_pixels;
        for (uint32_t x = 0U; x < params->width; ++x) {
            size_t i = (size_t)x * 2U;
            uint16_t word = (uint16_t)src_row[i] | ((uint16_t)src_row[i + 1U] << 8);
            dst_row[x] = (uint16_t)(word >> 4);
        }
    }
    return FRAMELAB_STATUS_OK;
}

FramelabStatus decode_mono16(const FramelabDecodeParams *params) {
    FramelabStatus status = validate_params(params, params->width * 2U);
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }

    for (uint32_t y = 0U; y < params->height; ++y) {
        const uint8_t *src_row = params->src + (size_t)y * params->src_stride_bytes;
        uint16_t *dst_row = params->dst + (size_t)y * params->dst_stride_pixels;
        for (uint32_t x = 0U; x < params->width; ++x) {
            size_t i = (size_t)x * 2U;
            dst_row[x] = (uint16_t)src_row[i] | ((uint16_t)src_row[i + 1U] << 8);
        }
    }
    return FRAMELAB_STATUS_OK;
}
