#include "framelab_native/decode/bayer_packed.h"
#include "framelab_native/decode/mono_packed.h"

FramelabStatus decode_bayer_rg12p(const FramelabDecodeParams *params) {
    return decode_mono12p(params);
}
