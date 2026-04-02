#include "framelab_native/common/simd.h"

#ifndef FRAMELAB_ENABLE_SIMD
#define FRAMELAB_ENABLE_SIMD 1
#endif

const char *framelab_simd_isa_name(FramelabSimdIsa isa) {
    switch (isa) {
        case FRAMELAB_SIMD_SSE2:
            return "sse2";
        case FRAMELAB_SIMD_NEON:
            return "neon";
        case FRAMELAB_SIMD_SCALAR:
        default:
            return "scalar";
    }
}

FramelabSimdIsa framelab_best_simd_isa(void) {
#if !FRAMELAB_ENABLE_SIMD
    return FRAMELAB_SIMD_SCALAR;
#elif defined(_M_X64) || defined(_M_AMD64)
    return FRAMELAB_SIMD_SSE2;
#elif defined(_M_IX86_FP) && _M_IX86_FP >= 2
    return FRAMELAB_SIMD_SSE2;
#elif defined(__aarch64__) || defined(__ARM_NEON)
    return FRAMELAB_SIMD_NEON;
#elif defined(__SSE2__)
#if defined(__GNUC__) || defined(__clang__)
    return __builtin_cpu_supports("sse2") ? FRAMELAB_SIMD_SSE2 : FRAMELAB_SIMD_SCALAR;
#else
    return FRAMELAB_SIMD_SSE2;
#endif
#else
    return FRAMELAB_SIMD_SCALAR;
#endif
}

FramelabSimdIsa framelab_resolve_decode_simd_isa(FramelabPixelFormat format, int simd_enabled) {
    if (!simd_enabled) {
        return FRAMELAB_SIMD_SCALAR;
    }
    switch (format) {
        case FRAMELAB_PIXFMT_MONO8:
        case FRAMELAB_PIXFMT_MONO10_LSB:
        case FRAMELAB_PIXFMT_MONO10_MSB:
        case FRAMELAB_PIXFMT_MONO12_LSB:
        case FRAMELAB_PIXFMT_MONO12_MSB:
        case FRAMELAB_PIXFMT_MONO16:
            return framelab_best_simd_isa();
        default:
            return FRAMELAB_SIMD_SCALAR;
    }
}
