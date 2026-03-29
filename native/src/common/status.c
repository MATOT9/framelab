#include "framelab_native/common/status.h"

const char *framelab_status_string(FramelabStatus status) {
    switch (status) {
        case FRAMELAB_STATUS_OK: return "ok";
        case FRAMELAB_STATUS_INVALID_ARGUMENT: return "invalid_argument";
        case FRAMELAB_STATUS_UNSUPPORTED_FORMAT: return "unsupported_format";
        case FRAMELAB_STATUS_SIZE_MISMATCH: return "size_mismatch";
        case FRAMELAB_STATUS_IO_ERROR: return "io_error";
        case FRAMELAB_STATUS_ALLOC_FAILED: return "alloc_failed";
        case FRAMELAB_STATUS_OUT_OF_RANGE: return "out_of_range";
        case FRAMELAB_STATUS_NOT_IMPLEMENTED: return "not_implemented";
        default: return "unknown_status";
    }
}
