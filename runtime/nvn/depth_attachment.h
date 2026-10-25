// Narrow proof for the opt-in no-FS path. No texture creation, view creation, or renderer state changes.
#pragma once
#include "nvn.h"

typedef struct {
    uint32_t width, height, levels, layers, samples;
    bool base_2d, attached_is_base, format_matches, subresource_zero;
} DepthAttachment;

// NVN uses zero for ordinary non-MSAA textures. Never infer safety from that convention alone: require the
// actual Metal sample count and the descriptor's pipeline sample count to agree on one. Rejected multi-sample
// values stay distinguishable from missing/mismatched metadata for diagnostic classification.
static inline uint32_t depth_attachment_samples(uint32_t raw, uint32_t actual, uint32_t pipeline) {
    if (raw > 1) return raw;
    if (actual > 1) return actual;
    if (pipeline > 1) return pipeline;
    return actual == 1 && pipeline == 1 ? 1 : 0;
}

// Accept only views equivalent to the full base 2D depth attachment. In addition to checking every declared
// field, require the real view_texture() result to be the base Metal object. A failed view creation returning
// its base cannot accidentally admit a changed format/range. Subset mip views remain excluded even at mip zero.
static inline bool depth_attachment_view(const NvnTexture *t, const NvnTextureView *v, bool has_view,
                                         const DepthAttachment *a) {
    if (!t || !a || t->target != 1 || !a->width || !a->height || !a->levels || a->layers != 1 ||
        !a->base_2d || !a->attached_is_base || !a->format_matches || !a->subresource_zero) return false;
    if (!has_view) return true;
    if (!v || (v->setmask & ~63u)) return false;
    if ((v->setmask & 1) && (v->base_level || (v->num_levels && v->num_levels != a->levels))) return false;
    if ((v->setmask & 2) && (v->min_layer || (v->num_layers && v->num_layers != 1))) return false;
    if ((v->setmask & 4) && v->format != t->format) return false;
    if ((v->setmask & 8) && memcmp(v->swizzle, t->swizzle, sizeof v->swizzle)) return false;
    if ((v->setmask & 16) && v->ds_mode != t->ds_mode) return false;
    if ((v->setmask & 32) && v->target != t->target) return false;
    return true;
}

#ifdef __OBJC__
#import <Metal/Metal.h>
// The exact descriptor about to be encoded, observed after normal view selection. Never make another view or
// ask the texture cache to resolve the base again. The ordinary draw path and standalone Metal tests share this.
static inline DepthAttachment depth_attachment_observe(id<MTLTexture> base, MTLRenderPassDescriptor *rp,
                                                       MTLPixelFormat expected) {
    id<MTLTexture> dt = rp.depthAttachment.texture, st = rp.stencilAttachment.texture;
    return (DepthAttachment){
        .width = (uint32_t)dt.width, .height = (uint32_t)dt.height,
        .levels = (uint32_t)base.mipmapLevelCount, .layers = (uint32_t)base.arrayLength,
        .samples = (uint32_t)dt.sampleCount, .base_2d = base && base.textureType == MTLTextureType2D,
        .attached_is_base = base && dt == base, .format_matches = base && base.pixelFormat == expected && dt.pixelFormat == expected,
        .subresource_zero = !rp.depthAttachment.level && !rp.depthAttachment.slice && !rp.depthAttachment.depthPlane &&
            (!st || (st == dt && !rp.stencilAttachment.level && !rp.stencilAttachment.slice && !rp.stencilAttachment.depthPlane))
    };
}
#endif
