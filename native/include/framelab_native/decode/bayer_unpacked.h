#ifndef FRAMELAB_NATIVE_DECODE_BAYER_UNPACKED_H
#define FRAMELAB_NATIVE_DECODE_BAYER_UNPACKED_H

#include "framelab_native/common/status.h"
#include "framelab_native/common/types.h"

#ifdef __cplusplus
extern "C" {
#endif

FramelabStatus decode_bayer_rg8(const FramelabDecodeParams *params);
FramelabStatus decode_bayer_rg12_lsb(const FramelabDecodeParams *params);
FramelabStatus decode_bayer_rg12_msb(const FramelabDecodeParams *params);
FramelabStatus decode_bayer_rg16(const FramelabDecodeParams *params);

#ifdef __cplusplus
}
#endif

#endif
