#ifndef FRAMELAB_NATIVE_LOADERS_RAW_SOURCE_H
#define FRAMELAB_NATIVE_LOADERS_RAW_SOURCE_H

#include <stddef.h>
#include <stdint.h>

#include "framelab_native/common/status.h"
#include "framelab_native/common/types.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct FramelabRawSource {
    const uint8_t *data;
    size_t size;
    uint32_t src_stride_bytes;
    int used_mmap;
    void *impl;
} FramelabRawSource;

uint32_t framelab_raw_bytes_per_row(FramelabPixelFormat format, uint32_t width);

FramelabStatus framelab_raw_source_open(const FramelabRawLoadParams *params,
                                        FramelabRawSource *source);

void framelab_raw_source_close(FramelabRawSource *source);

#ifdef __cplusplus
}
#endif

#endif
