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

static inline uint16_t framelab_unpack_mono10p_p0(uint8_t b0, uint8_t b1) {
    return (uint16_t)(b0 | ((uint16_t)(b1 & 0x03u) << 8));
}

static inline uint16_t framelab_unpack_mono10p_p1(uint8_t b1, uint8_t b2) {
    return (uint16_t)(((uint16_t)b1 >> 2) | ((uint16_t)(b2 & 0x0Fu) << 6));
}

static inline uint16_t framelab_unpack_mono10p_p2(uint8_t b2, uint8_t b3) {
    return (uint16_t)(((uint16_t)b2 >> 4) | ((uint16_t)(b3 & 0x3Fu) << 4));
}

static inline uint16_t framelab_unpack_mono10p_p3(uint8_t b3, uint8_t b4) {
    return (uint16_t)(((uint16_t)b3 >> 6) | ((uint16_t)b4 << 2));
}

static inline uint16_t framelab_unpack_mono10packed_p0(uint8_t b0, uint8_t b1) {
    return (uint16_t)(((uint16_t)b0 << 2) | (uint16_t)(b1 & 0x03u));
}

static inline uint16_t framelab_unpack_mono10packed_p1(uint8_t b1, uint8_t b2) {
    return (uint16_t)(((uint16_t)b2 << 2) | ((uint16_t)(b1 >> 4) & 0x03u));
}

static inline uint16_t framelab_unpack_mono12packed_p0(uint8_t b0, uint8_t b1) {
    return (uint16_t)(((uint16_t)b0 << 4) | (uint16_t)(b1 & 0x0Fu));
}

static inline uint16_t framelab_unpack_mono12packed_p1(uint8_t b1, uint8_t b2) {
    return (uint16_t)(((uint16_t)b2 << 4) | ((uint16_t)b1 >> 4));
}

#ifdef __cplusplus
}
#endif

#endif
