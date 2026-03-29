#ifndef FRAMELAB_NATIVE_METRICS_BACKGROUND_H
#define FRAMELAB_NATIVE_METRICS_BACKGROUND_H

#include "framelab_native/common/status.h"
#include "framelab_native/common/types.h"

#ifdef __cplusplus
extern "C" {
#endif

FramelabStatus framelab_apply_background_to_f32(const FramelabImageView *image,
                                                const FramelabImageView *background,
                                                FramelabBackgroundMode mode,
                                                float *dst,
                                                uint32_t dst_stride_floats);

#ifdef __cplusplus
}
#endif

#endif
