#ifndef FRAMELAB_NATIVE_LOADERS_RAW_LOADER_H
#define FRAMELAB_NATIVE_LOADERS_RAW_LOADER_H

#include "framelab_native/common/status.h"
#include "framelab_native/common/types.h"

#ifdef __cplusplus
extern "C" {
#endif

FramelabStatus framelab_load_raw_and_decode(const FramelabRawLoadParams *params,
                                            uint16_t *dst,
                                            uint32_t dst_stride_pixels);

#ifdef __cplusplus
}
#endif

#endif
