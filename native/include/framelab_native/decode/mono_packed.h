#ifndef FRAMELAB_NATIVE_DECODE_MONO_PACKED_H
#define FRAMELAB_NATIVE_DECODE_MONO_PACKED_H

#include "framelab_native/common/status.h"
#include "framelab_native/common/types.h"

#ifdef __cplusplus
extern "C" {
#endif

FramelabStatus decode_mono12p(const FramelabDecodeParams *params);

#ifdef __cplusplus
}
#endif

#endif
