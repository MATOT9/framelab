#include "framelab_native/common/dispatch.h"

int framelab_is_bayer_format(FramelabPixelFormat format) {
    switch (format) {
        case FRAMELAB_PIXFMT_BAYER_RG8:
        case FRAMELAB_PIXFMT_BAYER_RG12_LSB:
        case FRAMELAB_PIXFMT_BAYER_RG12_MSB:
        case FRAMELAB_PIXFMT_BAYER_RG12P:
        case FRAMELAB_PIXFMT_BAYER_RG16:
            return 1;
        default:
            return 0;
    }
}

int framelab_is_packed_format(FramelabPixelFormat format) {
    switch (format) {
        case FRAMELAB_PIXFMT_MONO12P:
        case FRAMELAB_PIXFMT_BAYER_RG12P:
            return 1;
        default:
            return 0;
    }
}
