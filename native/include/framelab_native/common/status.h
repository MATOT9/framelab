#ifndef FRAMELAB_NATIVE_COMMON_STATUS_H
#define FRAMELAB_NATIVE_COMMON_STATUS_H

#ifdef __cplusplus
extern "C" {
#endif

typedef enum FramelabStatus {
    FRAMELAB_STATUS_OK = 0,
    FRAMELAB_STATUS_INVALID_ARGUMENT = 1,
    FRAMELAB_STATUS_UNSUPPORTED_FORMAT = 2,
    FRAMELAB_STATUS_SIZE_MISMATCH = 3,
    FRAMELAB_STATUS_IO_ERROR = 4,
    FRAMELAB_STATUS_ALLOC_FAILED = 5,
    FRAMELAB_STATUS_OUT_OF_RANGE = 6,
    FRAMELAB_STATUS_NOT_IMPLEMENTED = 7
} FramelabStatus;

const char *framelab_status_string(FramelabStatus status);

#ifdef __cplusplus
}
#endif

#endif
