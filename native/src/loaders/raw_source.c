#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "file_map.h"
#include "framelab_native/loaders/raw_source.h"

typedef struct FramelabRawSourceImpl {
    uint8_t *buffer;
    size_t buffer_size;
    FramelabMappedFile mapped;
    int has_mapped_file;
} FramelabRawSourceImpl;

static uint32_t packed_row_bytes(uint32_t width, uint32_t bits_per_pixel) {
    uint64_t total_bits = (uint64_t)width * (uint64_t)bits_per_pixel;
    uint64_t total_bytes = (total_bits + 7U) / 8U;
    if (total_bytes > UINT32_MAX) {
        return 0U;
    }
    return (uint32_t)total_bytes;
}

uint32_t framelab_raw_bytes_per_row(FramelabPixelFormat format, uint32_t width) {
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

static FramelabStatus validate_open_params(
    const FramelabRawLoadParams *params,
    uint32_t *src_stride_bytes,
    size_t *needed_size
) {
    size_t payload_size;
    uint32_t stride;

    if (params == NULL || params->path == NULL || src_stride_bytes == NULL || needed_size == NULL) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    if (params->width == 0U || params->height == 0U) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    stride = params->src_stride_bytes;
    if (stride == 0U) {
        stride = framelab_raw_bytes_per_row(params->pixel_format, params->width);
    }
    if (stride == 0U) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    payload_size = (size_t)stride * (size_t)params->height;
    if (payload_size / (size_t)stride != (size_t)params->height) {
        return FRAMELAB_STATUS_OUT_OF_RANGE;
    }
    if (params->offset_bytes > SIZE_MAX - payload_size) {
        return FRAMELAB_STATUS_OUT_OF_RANGE;
    }
    *src_stride_bytes = stride;
    *needed_size = params->offset_bytes + payload_size;
    return FRAMELAB_STATUS_OK;
}

static void raw_source_reset(FramelabRawSource *source) {
    if (source == NULL) {
        return;
    }
    memset(source, 0, sizeof(*source));
}

static FramelabStatus open_buffered(
    const FramelabRawLoadParams *params,
    size_t needed_size,
    FramelabRawSource *source
) {
    FILE *fp = NULL;
    uint8_t *buffer = NULL;
    long file_size = 0L;
    size_t read_count;
    FramelabRawSourceImpl *impl = NULL;

    fp = fopen(params->path, "rb");
    if (fp == NULL) {
        return FRAMELAB_STATUS_IO_ERROR;
    }
    if (fseek(fp, 0L, SEEK_END) != 0) {
        fclose(fp);
        return FRAMELAB_STATUS_IO_ERROR;
    }
    file_size = ftell(fp);
    if (file_size < 0L || (size_t)file_size < needed_size) {
        fclose(fp);
        return FRAMELAB_STATUS_SIZE_MISMATCH;
    }
    if (fseek(fp, 0L, SEEK_SET) != 0) {
        fclose(fp);
        return FRAMELAB_STATUS_IO_ERROR;
    }
    buffer = (uint8_t *)malloc(needed_size);
    if (buffer == NULL) {
        fclose(fp);
        return FRAMELAB_STATUS_ALLOC_FAILED;
    }
    read_count = fread(buffer, 1U, needed_size, fp);
    fclose(fp);
    if (read_count != needed_size) {
        free(buffer);
        return FRAMELAB_STATUS_IO_ERROR;
    }
    impl = (FramelabRawSourceImpl *)calloc(1U, sizeof(*impl));
    if (impl == NULL) {
        free(buffer);
        return FRAMELAB_STATUS_ALLOC_FAILED;
    }
    impl->buffer = buffer;
    impl->buffer_size = needed_size;
    source->data = buffer;
    source->size = needed_size;
    source->used_mmap = 0;
    source->impl = impl;
    return FRAMELAB_STATUS_OK;
}

static FramelabStatus open_mapped(
    const FramelabRawLoadParams *params,
    FramelabRawSource *source
) {
    FramelabMappedFile mapped;
    FramelabRawSourceImpl *impl = NULL;
    FramelabStatus status;

    memset(&mapped, 0, sizeof(mapped));
    status = framelab_file_map_readonly(params->path, &mapped);
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }
    impl = (FramelabRawSourceImpl *)calloc(1U, sizeof(*impl));
    if (impl == NULL) {
        framelab_file_map_close(&mapped);
        return FRAMELAB_STATUS_ALLOC_FAILED;
    }
    impl->mapped = mapped;
    impl->has_mapped_file = 1;
    source->data = mapped.data;
    source->size = mapped.size;
    source->used_mmap = 1;
    source->impl = impl;
    return FRAMELAB_STATUS_OK;
}

FramelabStatus framelab_raw_source_open(
    const FramelabRawLoadParams *params,
    FramelabRawSource *source
) {
    uint32_t src_stride_bytes = 0U;
    size_t needed_size = 0U;
    FramelabStatus status;

    if (source == NULL) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    raw_source_reset(source);
    status = validate_open_params(params, &src_stride_bytes, &needed_size);
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }

    if (params->io_mode != FRAMELAB_RAW_IO_BUFFERED_ONLY && framelab_file_mapping_supported()) {
        status = open_mapped(params, source);
        if (status == FRAMELAB_STATUS_OK) {
            if (source->size < needed_size) {
                framelab_raw_source_close(source);
                return FRAMELAB_STATUS_SIZE_MISMATCH;
            }
            source->src_stride_bytes = src_stride_bytes;
            return FRAMELAB_STATUS_OK;
        }
        if (params->io_mode == FRAMELAB_RAW_IO_MMAP_ONLY) {
            return status;
        }
    } else if (params->io_mode == FRAMELAB_RAW_IO_MMAP_ONLY) {
        return FRAMELAB_STATUS_NOT_IMPLEMENTED;
    }

    status = open_buffered(params, needed_size, source);
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }
    source->src_stride_bytes = src_stride_bytes;
    return FRAMELAB_STATUS_OK;
}

void framelab_raw_source_close(FramelabRawSource *source) {
    FramelabRawSourceImpl *impl;

    if (source == NULL) {
        return;
    }
    impl = (FramelabRawSourceImpl *)source->impl;
    if (impl != NULL) {
        if (impl->has_mapped_file) {
            framelab_file_map_close(&impl->mapped);
        }
        if (impl->buffer != NULL) {
            free(impl->buffer);
        }
        free(impl);
    }
    raw_source_reset(source);
}
