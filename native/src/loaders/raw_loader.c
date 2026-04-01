#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>

#include "framelab_native/loaders/raw_loader.h"
#include "framelab_native/decode/decode.h"

static uint32_t packed_row_bytes(uint32_t width, uint32_t bits_per_pixel) {
    uint64_t total_bits = (uint64_t)width * (uint64_t)bits_per_pixel;
    uint64_t total_bytes = (total_bits + 7U) / 8U;
    if (total_bytes > UINT32_MAX) {
        return 0U;
    }
    return (uint32_t)total_bytes;
}

static uint32_t bytes_per_row_for_format(FramelabPixelFormat format, uint32_t width) {
    switch (format) {
        case FRAMELAB_PIXFMT_MONO8:
        case FRAMELAB_PIXFMT_BAYER_RG8:
            return width;
        case FRAMELAB_PIXFMT_MONO10_LSB:
        case FRAMELAB_PIXFMT_MONO10_MSB:
        case FRAMELAB_PIXFMT_MONO12_LSB:
        case FRAMELAB_PIXFMT_MONO12_MSB:
        case FRAMELAB_PIXFMT_MONO16:
        case FRAMELAB_PIXFMT_BAYER_RG12_LSB:
        case FRAMELAB_PIXFMT_BAYER_RG12_MSB:
        case FRAMELAB_PIXFMT_BAYER_RG16:
            return width * 2U;
        case FRAMELAB_PIXFMT_MONO10P:
        case FRAMELAB_PIXFMT_MONO10PACKED:
            return packed_row_bytes(width, 10U);
        case FRAMELAB_PIXFMT_MONO12P:
        case FRAMELAB_PIXFMT_MONO12PACKED:
        case FRAMELAB_PIXFMT_BAYER_RG12P:
            return packed_row_bytes(width, 12U);
        default:
            return 0U;
    }
}

FramelabStatus framelab_load_raw_and_decode(const FramelabRawLoadParams *params,
                                            uint16_t *dst,
                                            uint32_t dst_stride_pixels) {
    FILE *fp = NULL;
    long file_size = 0;
    uint8_t *buffer = NULL;
    FramelabStatus status = FRAMELAB_STATUS_OK;

    if (params == NULL || params->path == NULL || dst == NULL) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    if (params->width == 0U || params->height == 0U || dst_stride_pixels < params->width) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }

    uint32_t src_stride = params->src_stride_bytes;
    if (src_stride == 0U) {
        src_stride = bytes_per_row_for_format(params->pixel_format, params->width);
    }
    if (src_stride == 0U) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }

    size_t needed_size = params->offset_bytes + (size_t)src_stride * params->height;

    fp = fopen(params->path, "rb");
    if (fp == NULL) {
        return FRAMELAB_STATUS_IO_ERROR;
    }
    if (fseek(fp, 0L, SEEK_END) != 0) {
        status = FRAMELAB_STATUS_IO_ERROR;
        goto cleanup;
    }
    file_size = ftell(fp);
    if (file_size < 0 || (size_t)file_size < needed_size) {
        status = FRAMELAB_STATUS_SIZE_MISMATCH;
        goto cleanup;
    }
    if (fseek(fp, 0L, SEEK_SET) != 0) {
        status = FRAMELAB_STATUS_IO_ERROR;
        goto cleanup;
    }

    buffer = (uint8_t *)malloc((size_t)file_size);
    if (buffer == NULL) {
        status = FRAMELAB_STATUS_ALLOC_FAILED;
        goto cleanup;
    }
    if (fread(buffer, 1U, (size_t)file_size, fp) != (size_t)file_size) {
        status = FRAMELAB_STATUS_IO_ERROR;
        goto cleanup;
    }

    FramelabDecodeParams decode_params;
    memset(&decode_params, 0, sizeof(decode_params));
    decode_params.src = buffer + params->offset_bytes;
    decode_params.src_size = (size_t)file_size - params->offset_bytes;
    decode_params.width = params->width;
    decode_params.height = params->height;
    decode_params.src_stride_bytes = src_stride;
    decode_params.pixel_format = params->pixel_format;
    decode_params.dst = dst;
    decode_params.dst_stride_pixels = dst_stride_pixels;
    status = framelab_decode(&decode_params);

cleanup:
    if (buffer != NULL) {
        free(buffer);
    }
    if (fp != NULL) {
        fclose(fp);
    }
    return status;
}
