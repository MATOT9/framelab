#include "framelab_native/decode/bayer_unpacked.h"
#include "framelab_native/decode/mono_unpacked.h"

FramelabStatus decode_bayer_rg8(const FramelabDecodeParams *params) {
    return decode_mono8(params);
}

FramelabStatus decode_bayer_rg12_lsb(const FramelabDecodeParams *params) {
    return decode_mono12_lsb(params);
}

FramelabStatus decode_bayer_rg12_msb(const FramelabDecodeParams *params) {
    return decode_mono12_msb(params);
}

FramelabStatus decode_bayer_rg16(const FramelabDecodeParams *params) {
    return decode_mono16(params);
}
