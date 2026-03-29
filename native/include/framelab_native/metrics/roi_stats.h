#ifndef FRAMELAB_NATIVE_METRICS_ROI_STATS_H
#define FRAMELAB_NATIVE_METRICS_ROI_STATS_H

#include "framelab_native/common/status.h"
#include "framelab_native/common/types.h"

#ifdef __cplusplus
extern "C" {
#endif

FramelabStatus framelab_compute_roi_stats(const FramelabImageView *image,
                                          const FramelabRoi *roi,
                                          double *out_mean,
                                          double *out_stddev,
                                          uint64_t *out_count);

#ifdef __cplusplus
}
#endif

#endif
