#ifndef FRAMELAB_NATIVE_COMMON_ROI_H
#define FRAMELAB_NATIVE_COMMON_ROI_H

#include "framelab_native/common/types.h"

#ifdef __cplusplus
extern "C" {
#endif

int framelab_roi_is_valid(const FramelabRoi *roi, uint32_t width, uint32_t height);
int framelab_roi_contains(const FramelabRoi *roi, int32_t x, int32_t y);

#ifdef __cplusplus
}
#endif

#endif
