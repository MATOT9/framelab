#ifndef FRAMELAB_NATIVE_DECODE_DECODE_H
#define FRAMELAB_NATIVE_DECODE_DECODE_H

#include "framelab_native/common/status.h"
#include "framelab_native/common/types.h"

#ifdef __cplusplus
extern "C" {
#endif

FramelabStatus framelab_decode(const FramelabDecodeParams *params);

#ifdef __cplusplus
}
#endif

#endif
