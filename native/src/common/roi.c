#include "framelab_native/common/roi.h"

int framelab_roi_is_valid(const FramelabRoi *roi, uint32_t width, uint32_t height) {
    if (roi == NULL) {
        return 1;
    }
    if (roi->x0 < 0 || roi->y0 < 0 || roi->x1 <= roi->x0 || roi->y1 <= roi->y0) {
        return 0;
    }
    if ((uint32_t)roi->x1 > width || (uint32_t)roi->y1 > height) {
        return 0;
    }
    return 1;
}

int framelab_roi_contains(const FramelabRoi *roi, int32_t x, int32_t y) {
    if (roi == NULL) {
        return 1;
    }
    return x >= roi->x0 && x < roi->x1 && y >= roi->y0 && y < roi->y1;
}
