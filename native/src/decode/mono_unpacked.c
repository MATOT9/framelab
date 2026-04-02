#include <stddef.h>
#include <stdint.h>

#include "framelab_native/common/simd.h"
#include "framelab_native/decode/mono_unpacked.h"

#ifndef FRAMELAB_ENABLE_SIMD
#define FRAMELAB_ENABLE_SIMD 1
#endif

#if FRAMELAB_ENABLE_SIMD && (defined(_M_X64) || defined(_M_AMD64) || defined(__SSE2__) || (defined(_M_IX86_FP) && _M_IX86_FP >= 2))
#define FRAMELAB_HAVE_SSE2 1
#include <emmintrin.h>
#else
#define FRAMELAB_HAVE_SSE2 0
#endif

#if FRAMELAB_ENABLE_SIMD && (defined(__aarch64__) || defined(__ARM_NEON))
#define FRAMELAB_HAVE_NEON 1
#include <arm_neon.h>
#else
#define FRAMELAB_HAVE_NEON 0
#endif

static FramelabStatus validate_params(const FramelabDecodeParams *params, uint32_t min_stride_bytes) {
    if (params == NULL || params->src == NULL || params->dst == NULL) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    if (params->width == 0U || params->height == 0U) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    if (params->src_stride_bytes < min_stride_bytes) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    if (params->dst_stride_pixels < params->width) {
        return FRAMELAB_STATUS_INVALID_ARGUMENT;
    }
    return FRAMELAB_STATUS_OK;
}

static FramelabSimdIsa decode_simd_isa(const FramelabDecodeParams *params) {
    return framelab_resolve_decode_simd_isa(params->pixel_format, params->simd_enabled);
}

#if FRAMELAB_HAVE_SSE2
static void decode_mono8_sse2_row(const uint8_t *src_row, uint16_t *dst_row, uint32_t width) {
    uint32_t x = 0U;
    const __m128i zero = _mm_setzero_si128();

    for (; x + 16U <= width; x += 16U) {
        __m128i bytes = _mm_loadu_si128((const __m128i *)(src_row + x));
        __m128i low = _mm_unpacklo_epi8(bytes, zero);
        __m128i high = _mm_unpackhi_epi8(bytes, zero);
        _mm_storeu_si128((__m128i *)(dst_row + x), low);
        _mm_storeu_si128((__m128i *)(dst_row + x + 8U), high);
    }
    for (; x < width; ++x) {
        dst_row[x] = src_row[x];
    }
}

static void decode_u16_sse2_row(const uint8_t *src_row,
                                uint16_t *dst_row,
                                uint32_t width,
                                uint16_t mask,
                                int shift_right_bits) {
    uint32_t x = 0U;
    const __m128i mask_vec = _mm_set1_epi16((short)mask);

    for (; x + 8U <= width; x += 8U) {
        __m128i words = _mm_loadu_si128((const __m128i *)(src_row + (size_t)x * 2U));
        if (shift_right_bits > 0) {
            words = _mm_srli_epi16(words, shift_right_bits);
        } else if (mask != 0xFFFFu) {
            words = _mm_and_si128(words, mask_vec);
        }
        _mm_storeu_si128((__m128i *)(dst_row + x), words);
    }
    for (; x < width; ++x) {
        size_t i = (size_t)x * 2U;
        uint16_t word = (uint16_t)src_row[i] | ((uint16_t)src_row[i + 1U] << 8);
        if (shift_right_bits > 0) {
            dst_row[x] = (uint16_t)(word >> shift_right_bits);
        } else {
            dst_row[x] = (uint16_t)(word & mask);
        }
    }
}
#endif

#if FRAMELAB_HAVE_NEON
static void decode_mono8_neon_row(const uint8_t *src_row, uint16_t *dst_row, uint32_t width) {
    uint32_t x = 0U;

    for (; x + 16U <= width; x += 16U) {
        uint8x16_t bytes = vld1q_u8(src_row + x);
        vst1q_u16(dst_row + x, vmovl_u8(vget_low_u8(bytes)));
        vst1q_u16(dst_row + x + 8U, vmovl_u8(vget_high_u8(bytes)));
    }
    for (; x < width; ++x) {
        dst_row[x] = src_row[x];
    }
}

static void decode_u16_neon_row(const uint8_t *src_row,
                                uint16_t *dst_row,
                                uint32_t width,
                                uint16_t mask,
                                int shift_right_bits) {
    uint32_t x = 0U;
    const uint16x8_t mask_vec = vdupq_n_u16(mask);

    for (; x + 8U <= width; x += 8U) {
        uint16x8_t words = vld1q_u16((const uint16_t *)(src_row + (size_t)x * 2U));
        if (shift_right_bits > 0) {
            switch (shift_right_bits) {
                case 4:
                    words = vshrq_n_u16(words, 4);
                    break;
                case 6:
                    words = vshrq_n_u16(words, 6);
                    break;
                default:
                    break;
            }
        } else if (mask != 0xFFFFu) {
            words = vandq_u16(words, mask_vec);
        }
        vst1q_u16(dst_row + x, words);
    }
    for (; x < width; ++x) {
        size_t i = (size_t)x * 2U;
        uint16_t word = (uint16_t)src_row[i] | ((uint16_t)src_row[i + 1U] << 8);
        if (shift_right_bits > 0) {
            dst_row[x] = (uint16_t)(word >> shift_right_bits);
        } else {
            dst_row[x] = (uint16_t)(word & mask);
        }
    }
}
#endif

FramelabStatus decode_mono8(const FramelabDecodeParams *params) {
    FramelabStatus status = validate_params(params, params->width);
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }

    for (uint32_t y = 0U; y < params->height; ++y) {
        const uint8_t *src_row = params->src + (size_t)y * params->src_stride_bytes;
        uint16_t *dst_row = params->dst + (size_t)y * params->dst_stride_pixels;
        switch (decode_simd_isa(params)) {
#if FRAMELAB_HAVE_SSE2
            case FRAMELAB_SIMD_SSE2:
                decode_mono8_sse2_row(src_row, dst_row, params->width);
                break;
#endif
#if FRAMELAB_HAVE_NEON
            case FRAMELAB_SIMD_NEON:
                decode_mono8_neon_row(src_row, dst_row, params->width);
                break;
#endif
            default:
                for (uint32_t x = 0U; x < params->width; ++x) {
                    dst_row[x] = src_row[x];
                }
                break;
        }
    }
    return FRAMELAB_STATUS_OK;
}

FramelabStatus decode_mono10_lsb(const FramelabDecodeParams *params) {
    FramelabStatus status = validate_params(params, params->width * 2U);
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }

    for (uint32_t y = 0U; y < params->height; ++y) {
        const uint8_t *src_row = params->src + (size_t)y * params->src_stride_bytes;
        uint16_t *dst_row = params->dst + (size_t)y * params->dst_stride_pixels;
        switch (decode_simd_isa(params)) {
#if FRAMELAB_HAVE_SSE2
            case FRAMELAB_SIMD_SSE2:
                decode_u16_sse2_row(src_row, dst_row, params->width, 0x03FFu, 0);
                break;
#endif
#if FRAMELAB_HAVE_NEON
            case FRAMELAB_SIMD_NEON:
                decode_u16_neon_row(src_row, dst_row, params->width, 0x03FFu, 0);
                break;
#endif
            default:
                for (uint32_t x = 0U; x < params->width; ++x) {
                    size_t i = (size_t)x * 2U;
                    uint16_t word = (uint16_t)src_row[i] | ((uint16_t)src_row[i + 1U] << 8);
                    dst_row[x] = (uint16_t)(word & 0x03FFu);
                }
                break;
        }
    }
    return FRAMELAB_STATUS_OK;
}

FramelabStatus decode_mono10_msb(const FramelabDecodeParams *params) {
    FramelabStatus status = validate_params(params, params->width * 2U);
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }

    for (uint32_t y = 0U; y < params->height; ++y) {
        const uint8_t *src_row = params->src + (size_t)y * params->src_stride_bytes;
        uint16_t *dst_row = params->dst + (size_t)y * params->dst_stride_pixels;
        switch (decode_simd_isa(params)) {
#if FRAMELAB_HAVE_SSE2
            case FRAMELAB_SIMD_SSE2:
                decode_u16_sse2_row(src_row, dst_row, params->width, 0xFFFFu, 6);
                break;
#endif
#if FRAMELAB_HAVE_NEON
            case FRAMELAB_SIMD_NEON:
                decode_u16_neon_row(src_row, dst_row, params->width, 0xFFFFu, 6);
                break;
#endif
            default:
                for (uint32_t x = 0U; x < params->width; ++x) {
                    size_t i = (size_t)x * 2U;
                    uint16_t word = (uint16_t)src_row[i] | ((uint16_t)src_row[i + 1U] << 8);
                    dst_row[x] = (uint16_t)(word >> 6);
                }
                break;
        }
    }
    return FRAMELAB_STATUS_OK;
}

FramelabStatus decode_mono12_lsb(const FramelabDecodeParams *params) {
    FramelabStatus status = validate_params(params, params->width * 2U);
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }

    for (uint32_t y = 0U; y < params->height; ++y) {
        const uint8_t *src_row = params->src + (size_t)y * params->src_stride_bytes;
        uint16_t *dst_row = params->dst + (size_t)y * params->dst_stride_pixels;
        switch (decode_simd_isa(params)) {
#if FRAMELAB_HAVE_SSE2
            case FRAMELAB_SIMD_SSE2:
                decode_u16_sse2_row(src_row, dst_row, params->width, 0x0FFFu, 0);
                break;
#endif
#if FRAMELAB_HAVE_NEON
            case FRAMELAB_SIMD_NEON:
                decode_u16_neon_row(src_row, dst_row, params->width, 0x0FFFu, 0);
                break;
#endif
            default:
                for (uint32_t x = 0U; x < params->width; ++x) {
                    size_t i = (size_t)x * 2U;
                    uint16_t word = (uint16_t)src_row[i] | ((uint16_t)src_row[i + 1U] << 8);
                    dst_row[x] = (uint16_t)(word & 0x0FFFu);
                }
                break;
        }
    }
    return FRAMELAB_STATUS_OK;
}

FramelabStatus decode_mono12_msb(const FramelabDecodeParams *params) {
    FramelabStatus status = validate_params(params, params->width * 2U);
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }

    for (uint32_t y = 0U; y < params->height; ++y) {
        const uint8_t *src_row = params->src + (size_t)y * params->src_stride_bytes;
        uint16_t *dst_row = params->dst + (size_t)y * params->dst_stride_pixels;
        switch (decode_simd_isa(params)) {
#if FRAMELAB_HAVE_SSE2
            case FRAMELAB_SIMD_SSE2:
                decode_u16_sse2_row(src_row, dst_row, params->width, 0xFFFFu, 4);
                break;
#endif
#if FRAMELAB_HAVE_NEON
            case FRAMELAB_SIMD_NEON:
                decode_u16_neon_row(src_row, dst_row, params->width, 0xFFFFu, 4);
                break;
#endif
            default:
                for (uint32_t x = 0U; x < params->width; ++x) {
                    size_t i = (size_t)x * 2U;
                    uint16_t word = (uint16_t)src_row[i] | ((uint16_t)src_row[i + 1U] << 8);
                    dst_row[x] = (uint16_t)(word >> 4);
                }
                break;
        }
    }
    return FRAMELAB_STATUS_OK;
}

FramelabStatus decode_mono16(const FramelabDecodeParams *params) {
    FramelabStatus status = validate_params(params, params->width * 2U);
    if (status != FRAMELAB_STATUS_OK) {
        return status;
    }

    for (uint32_t y = 0U; y < params->height; ++y) {
        const uint8_t *src_row = params->src + (size_t)y * params->src_stride_bytes;
        uint16_t *dst_row = params->dst + (size_t)y * params->dst_stride_pixels;
        switch (decode_simd_isa(params)) {
#if FRAMELAB_HAVE_SSE2
            case FRAMELAB_SIMD_SSE2:
                decode_u16_sse2_row(src_row, dst_row, params->width, 0xFFFFu, 0);
                break;
#endif
#if FRAMELAB_HAVE_NEON
            case FRAMELAB_SIMD_NEON:
                decode_u16_neon_row(src_row, dst_row, params->width, 0xFFFFu, 0);
                break;
#endif
            default:
                for (uint32_t x = 0U; x < params->width; ++x) {
                    size_t i = (size_t)x * 2U;
                    dst_row[x] = (uint16_t)src_row[i] | ((uint16_t)src_row[i + 1U] << 8);
                }
                break;
        }
    }
    return FRAMELAB_STATUS_OK;
}
