#include <limits.h>

#include "framelab_native/common/stride.h"

int framelab_validate_nonzero_u32(uint32_t value) {
    return value != 0U;
}

int framelab_validate_multiplication_size(size_t a, size_t b, size_t *out) {
    if (out == NULL) {
        return 0;
    }
    if (a == 0U || b == 0U) {
        *out = 0U;
        return 1;
    }
    if (a > SIZE_MAX / b) {
        return 0;
    }
    *out = a * b;
    return 1;
}
