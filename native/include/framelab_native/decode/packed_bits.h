#ifndef FRAMELAB_NATIVE_DECODE_PACKED_BITS_H
#define FRAMELAB_NATIVE_DECODE_PACKED_BITS_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

static inline uint16_t framelab_unpack_mono12p_p0(uint8_t b0, uint8_t b1) {
    return (uint16_t)(b0 | ((uint16_t)(b1 & 0x0Fu) << 8));
}

static inline uint16_t framelab_unpack_mono12p_p1(uint8_t b1, uint8_t b2) {
    return (uint16_t)(((uint16_t)b1 >> 4) | ((uint16_t)b2 << 4));
}

#ifdef __cplusplus
}
#endif

#endif
