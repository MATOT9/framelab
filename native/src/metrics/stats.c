#include <math.h>

#include "framelab_native/metrics/stats.h"

void framelab_running_stats_init(FramelabRunningStats *stats) {
    stats->count = 0U;
    stats->nonzero_count = 0U;
    stats->min_value = 0.0;
    stats->max_value = 0.0;
    stats->min_nonzero = 0.0;
    stats->sum = 0.0;
    stats->mean = 0.0;
    stats->m2 = 0.0;
}

void framelab_running_stats_update(FramelabRunningStats *stats, double value) {
    stats->count += 1U;
    if (stats->count == 1U) {
        stats->min_value = value;
        stats->max_value = value;
    } else {
        if (value < stats->min_value) {
            stats->min_value = value;
        }
        if (value > stats->max_value) {
            stats->max_value = value;
        }
    }

    if (value != 0.0) {
        stats->nonzero_count += 1U;
        if (stats->nonzero_count == 1U || value < stats->min_nonzero) {
            stats->min_nonzero = value;
        }
    }

    stats->sum += value;
    double delta = value - stats->mean;
    stats->mean += delta / (double)stats->count;
    double delta2 = value - stats->mean;
    stats->m2 += delta * delta2;
}

double framelab_running_stats_stddev(const FramelabRunningStats *stats) {
    if (stats->count < 2U) {
        return 0.0;
    }
    return sqrt(stats->m2 / (double)stats->count);
}
