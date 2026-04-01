#ifndef FRAMELAB_NATIVE_DECODE_MONO_UNPACKED_H
#define FRAMELAB_NATIVE_DECODE_MONO_UNPACKED_H

#include "framelab_native/common/status.h"
#include "framelab_native/common/types.h"

#ifdef __cplusplus
extern "C" {
#endif

FramelabStatus decode_mono8(const FramelabDecodeParams *params);
FramelabStatus decode_mono10_lsb(const FramelabDecodeParams *params);
FramelabStatus decode_mono10_msb(const FramelabDecodeParams *params);
FramelabStatus decode_mono12_lsb(const FramelabDecodeParams *params);
FramelabStatus decode_mono12_msb(const FramelabDecodeParams *params);
FramelabStatus decode_mono16(const FramelabDecodeParams *params);

#ifdef __cplusplus
}
#endif

#endif
