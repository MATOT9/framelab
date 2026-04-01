#include <ctype.h>
#include <string.h>

#include "framelab_native/common/pixel_formats.h"

const char *framelab_pixel_format_name(FramelabPixelFormat format) {
    switch (format) {
        case FRAMELAB_PIXFMT_MONO8: return "mono8";
        case FRAMELAB_PIXFMT_MONO10_LSB: return "mono10_lsb";
        case FRAMELAB_PIXFMT_MONO10_MSB: return "mono10_msb";
        case FRAMELAB_PIXFMT_MONO10P: return "mono10p";
        case FRAMELAB_PIXFMT_MONO10PACKED: return "mono10packed";
        case FRAMELAB_PIXFMT_MONO12_LSB: return "mono12_lsb";
        case FRAMELAB_PIXFMT_MONO12_MSB: return "mono12_msb";
        case FRAMELAB_PIXFMT_MONO12P: return "mono12p";
        case FRAMELAB_PIXFMT_MONO12PACKED: return "mono12packed";
        case FRAMELAB_PIXFMT_MONO16: return "mono16";
        case FRAMELAB_PIXFMT_BAYER_RG8: return "bayer_rg8";
        case FRAMELAB_PIXFMT_BAYER_RG12_LSB: return "bayer_rg12_lsb";
        case FRAMELAB_PIXFMT_BAYER_RG12_MSB: return "bayer_rg12_msb";
        case FRAMELAB_PIXFMT_BAYER_RG12P: return "bayer_rg12p";
        case FRAMELAB_PIXFMT_BAYER_RG16: return "bayer_rg16";
        default: return "unknown";
    }
}

static int strings_equal_ci(const char *a, const char *b) {
    while (*a != '\0' && *b != '\0') {
        if (tolower((unsigned char)*a) != tolower((unsigned char)*b)) {
            return 0;
        }
        ++a;
        ++b;
    }
    return *a == '\0' && *b == '\0';
}

FramelabPixelFormat framelab_pixel_format_from_string(const char *name) {
    if (name == NULL) {
        return FRAMELAB_PIXFMT_UNKNOWN;
    }

    if (strings_equal_ci(name, "mono8")) return FRAMELAB_PIXFMT_MONO8;
    if (strings_equal_ci(name, "mono10") || strings_equal_ci(name, "mono10_msb") || strings_equal_ci(name, "mono10msb")) return FRAMELAB_PIXFMT_MONO10_MSB;
    if (strings_equal_ci(name, "mono10_lsb") || strings_equal_ci(name, "mono10lsb")) return FRAMELAB_PIXFMT_MONO10_LSB;
    if (strings_equal_ci(name, "mono10p")) return FRAMELAB_PIXFMT_MONO10P;
    if (strings_equal_ci(name, "mono10packed") || strings_equal_ci(name, "mono10_packed")) return FRAMELAB_PIXFMT_MONO10PACKED;
    if (strings_equal_ci(name, "mono12") || strings_equal_ci(name, "mono12_msb") || strings_equal_ci(name, "mono12msb")) return FRAMELAB_PIXFMT_MONO12_MSB;
    if (strings_equal_ci(name, "mono12_lsb") || strings_equal_ci(name, "mono12lsb")) return FRAMELAB_PIXFMT_MONO12_LSB;
    if (strings_equal_ci(name, "mono12p")) return FRAMELAB_PIXFMT_MONO12P;
    if (strings_equal_ci(name, "mono12packed") || strings_equal_ci(name, "mono12_packed")) return FRAMELAB_PIXFMT_MONO12PACKED;
    if (strings_equal_ci(name, "mono16")) return FRAMELAB_PIXFMT_MONO16;
    if (strings_equal_ci(name, "bayer_rg8")) return FRAMELAB_PIXFMT_BAYER_RG8;
    if (strings_equal_ci(name, "bayer_rg12_lsb") || strings_equal_ci(name, "bayerrg12lsb")) return FRAMELAB_PIXFMT_BAYER_RG12_LSB;
    if (strings_equal_ci(name, "bayer_rg12_msb") || strings_equal_ci(name, "bayerrg12msb")) return FRAMELAB_PIXFMT_BAYER_RG12_MSB;
    if (strings_equal_ci(name, "bayer_rg12p") || strings_equal_ci(name, "bayerrg12p")) return FRAMELAB_PIXFMT_BAYER_RG12P;
    if (strings_equal_ci(name, "bayer_rg16")) return FRAMELAB_PIXFMT_BAYER_RG16;
    return FRAMELAB_PIXFMT_UNKNOWN;
}
