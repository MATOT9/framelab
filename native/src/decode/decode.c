#include "framelab_native/decode/decode.h"
#include "framelab_native/decode/mono_unpacked.h"
#include "framelab_native/decode/mono_packed.h"
#include "framelab_native/decode/bayer_unpacked.h"
#include "framelab_native/decode/bayer_packed.h"

FramelabStatus framelab_decode(const FramelabDecodeParams *params) {
    if (params == NULL || params->src == NULL || params->dst == NULL) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }

    switch (params->pixel_format) {
        case FRAMELAB_PIXFMT_MONO8:
            return decode_mono8(params);
        case FRAMELAB_PIXFMT_MONO12_LSB:
            return decode_mono12_lsb(params);
        case FRAMELAB_PIXFMT_MONO12_MSB:
            return decode_mono12_msb(params);
        case FRAMELAB_PIXFMT_MONO12P:
            return decode_mono12p(params);
        case FRAMELAB_PIXFMT_MONO16:
            return decode_mono16(params);
        case FRAMELAB_PIXFMT_BAYER_RG8:
            return decode_bayer_rg8(params);
        case FRAMELAB_PIXFMT_BAYER_RG12_LSB:
            return decode_bayer_rg12_lsb(params);
        case FRAMELAB_PIXFMT_BAYER_RG12_MSB:
            return decode_bayer_rg12_msb(params);
        case FRAMELAB_PIXFMT_BAYER_RG12P:
            return decode_bayer_rg12p(params);
        case FRAMELAB_PIXFMT_BAYER_RG16:
            return decode_bayer_rg16(params);
        default:
            return FRAMELAB_STATUS_UNSUPPORTED_FORMAT;
    }
}
