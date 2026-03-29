#ifndef FRAMELAB_NATIVE_METRICS_HISTOGRAM_H
#define FRAMELAB_NATIVE_METRICS_HISTOGRAM_H

#include "framelab_native/common/status.h"
#include "framelab_native/common/types.h"

#ifdef __cplusplus
extern "C" {
#endif

FramelabStatus framelab_compute_histogram(const FramelabImageView *image,
                                          double value_min,
                                          double value_max,
                                          uint32_t bin_count,
                                          uint64_t *bins);

#ifdef __cplusplus
}
#endif

#endif
