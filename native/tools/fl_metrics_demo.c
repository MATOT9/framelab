#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "framelab_native/api.h"
#include "framelab_native/common/pixel_formats.h"

static int write_pgm8_preview(const char *path, const uint16_t *image, uint32_t width, uint32_t height) {
    FILE *fp = fopen(path, "wb");
    if (fp == NULL) {
        return 0;
    }
    fprintf(fp, "P5\n%u %u\n255\n", width, height);
    for (uint32_t y = 0U; y < height; ++y) {
        const uint16_t *row = image + (size_t)y * width;
        for (uint32_t x = 0U; x < width; ++x) {
            unsigned char v = (unsigned char)((row[x] * 255U) / 65535U);
            fwrite(&v, 1U, 1U, fp);
        }
    }
    fclose(fp);
    return 1;
}

int main(int argc, char **argv) {
    if (argc < 6) {
        fprintf(stderr, "Usage: %s <raw_path> <pixel_format> <width> <height> <stride_bytes> [preview_out.pgm]\n", argv[0]);
        return 1;
    }

    const char *raw_path = argv[1];
    FramelabPixelFormat fmt = framelab_pixel_format_from_string(argv[2]);
    uint32_t width = (uint32_t)strtoul(argv[3], NULL, 10);
    uint32_t height = (uint32_t)strtoul(argv[4], NULL, 10);
    uint32_t stride_bytes = (uint32_t)strtoul(argv[5], NULL, 10);

    if (fmt == FRAMELAB_PIXFMT_UNKNOWN) {
        fprintf(stderr, "Unknown pixel format: %s\n", argv[2]);
        return 1;
    }

    uint16_t *decoded = (uint16_t *)calloc((size_t)width * height, sizeof(uint16_t));
    if (decoded == NULL) {
        fprintf(stderr, "Allocation failed\n");
        return 1;
    }

    FramelabRawLoadParams load_params;
    memset(&load_params, 0, sizeof(load_params));
    load_params.path = raw_path;
    load_params.width = width;
    load_params.height = height;
    load_params.src_stride_bytes = stride_bytes;
    load_params.offset_bytes = 0U;
    load_params.pixel_format = fmt;

    FramelabStatus status = framelab_load_raw_and_decode(&load_params, decoded, width);
    if (status != FRAMELAB_STATUS_OK) {
        fprintf(stderr, "Decode failed: %s\n", framelab_status_string(status));
        free(decoded);
        return 1;
    }

    FramelabImageView view;
    view.data = decoded;
    view.width = width;
    view.height = height;
    view.stride_bytes = width * sizeof(uint16_t);
    view.sample_type = FRAMELAB_SAMPLE_U16;

    uint64_t hist[16];
    FramelabMetricsParams metric_params;
    memset(&metric_params, 0, sizeof(metric_params));
    metric_params.image = view;
    metric_params.background = NULL;
    metric_params.background_mode = FRAMELAB_BG_NONE;
    metric_params.roi = NULL;
    metric_params.use_threshold = 1;
    metric_params.threshold = 2048.0;
    metric_params.use_histogram = 1;
    metric_params.histogram_min = 0.0;
    metric_params.histogram_max = 65535.0;
    metric_params.histogram_bin_count = 16U;
    metric_params.histogram_bins = hist;

    FramelabMetricsResult result;
    status = framelab_compute_metrics(&metric_params, &result);
    if (status != FRAMELAB_STATUS_OK) {
        fprintf(stderr, "Metrics failed: %s\n", framelab_status_string(status));
        free(decoded);
        return 1;
    }

    printf("pixel_count      : %llu\n", (unsigned long long)result.pixel_count);
    printf("nonzero_count    : %llu\n", (unsigned long long)result.nonzero_count);
    printf("threshold_count  : %llu\n", (unsigned long long)result.threshold_count);
    printf("min_value        : %.3f\n", result.min_value);
    printf("max_value        : %.3f\n", result.max_value);
    printf("min_nonzero      : %.3f\n", result.min_nonzero);
    printf("mean             : %.3f\n", result.mean);
    printf("stddev           : %.3f\n", result.stddev);

    printf("histogram        :");
    for (size_t i = 0; i < 16U; ++i) {
        printf(" %llu", (unsigned long long)hist[i]);
    }
    printf("\n");

    if (argc >= 7) {
        if (!write_pgm8_preview(argv[6], decoded, width, height)) {
            fprintf(stderr, "Failed to write preview\n");
        }
    }

    free(decoded);
    return 0;
}
