#ifndef FRAMELAB_NATIVE_COMMON_SIMD_H
#define FRAMELAB_NATIVE_COMMON_SIMD_H

#include "framelab_native/common/pixel_formats.h"
#include "framelab_native/common/types.h"

#ifdef __cplusplus
extern "C" {
#endif

const char *framelab_simd_isa_name(FramelabSimdIsa isa);
FramelabSimdIsa framelab_best_simd_isa(void);
FramelabSimdIsa framelab_resolve_decode_simd_isa(FramelabPixelFormat format, int simd_enabled);

#ifdef __cplusplus
}
#endif

#endif
