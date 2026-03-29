#ifndef FRAMELAB_NATIVE_METRICS_STATS_H
#define FRAMELAB_NATIVE_METRICS_STATS_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct FramelabRunningStats {
    uint64_t count;
    uint64_t nonzero_count;
    double min_value;
    double max_value;
    double min_nonzero;
    double sum;
    double mean;
    double m2;
} FramelabRunningStats;

void framelab_running_stats_init(FramelabRunningStats *stats);
void framelab_running_stats_update(FramelabRunningStats *stats, double value);
double framelab_running_stats_stddev(const FramelabRunningStats *stats);

#ifdef __cplusplus
}
#endif

#endif
