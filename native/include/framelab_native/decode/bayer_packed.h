#ifndef FRAMELAB_NATIVE_DECODE_BAYER_PACKED_H
#define FRAMELAB_NATIVE_DECODE_BAYER_PACKED_H

#include "framelab_native/common/status.h"
#include "framelab_native/common/types.h"

#ifdef __cplusplus
extern "C" {
#endif

FramelabStatus decode_bayer_rg12p(const FramelabDecodeParams *params);

#ifdef __cplusplus
}
#endif

#endif
