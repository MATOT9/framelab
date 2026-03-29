#ifndef FRAMELAB_NATIVE_COMMON_DISPATCH_H
#define FRAMELAB_NATIVE_COMMON_DISPATCH_H

#include "framelab_native/common/pixel_formats.h"

#ifdef __cplusplus
extern "C" {
#endif

int framelab_is_bayer_format(FramelabPixelFormat format);
int framelab_is_packed_format(FramelabPixelFormat format);

#ifdef __cplusplus
}
#endif

#endif
