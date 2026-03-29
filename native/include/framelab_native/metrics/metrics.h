#ifndef FRAMELAB_NATIVE_METRICS_METRICS_H
#define FRAMELAB_NATIVE_METRICS_METRICS_H

#include "framelab_native/common/status.h"
#include "framelab_native/common/types.h"

#ifdef __cplusplus
extern "C" {
#endif

FramelabStatus framelab_compute_metrics(const FramelabMetricsParams *params,
                                        FramelabMetricsResult *result);

#ifdef __cplusplus
}
#endif

#endif
