#ifndef FRAMELAB_NATIVE_COMMON_STRIDE_H
#define FRAMELAB_NATIVE_COMMON_STRIDE_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

int framelab_validate_nonzero_u32(uint32_t value);
int framelab_validate_multiplication_size(size_t a, size_t b, size_t *out);

#ifdef __cplusplus
}
#endif

#endif
