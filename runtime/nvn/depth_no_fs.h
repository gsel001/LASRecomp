// Opt-in Metal experiment: never use the looser probe count as authorization to omit a fragment stage.
#pragma once
#include "depth_probe.h"

// NVIDIA's SPH specification: CommonWord0 and the PS output word at SPH+0x4c.
// https://nvidia.github.io/open-gpu-doc/Shader-Program-Header/Shader-Program-Header.html
// Only the type-2, version-3 pixel header is admitted; reject reserved bits and declared kills/stores/coverage.
// The certificate describes this translator's emitted MSL: color outputs only, no externally visible side effects.
static inline bool depth_no_fs_certify(const ShaderInfo *fs, uint32_t header, uint32_t outputs, bool debug) {
    if (!fs || debug || fs->writes_sample_mask || !fs->num_insts || outputs ||
        (header & 31u) != 2 || ((header >> 5) & 31u) != 3 || ((header >> 10) & 15u) != 5 ||
        (header & ((1u << 15) | (1u << 16) | (31u << 21) | (15u << 28)))) return false;
    DepthProbeDraw d = {.fs = fs, .width = 1, .height = 1, .samples = 1, .has_depth = true};
    return depth_probe_exclusions(&d) == 0;
}

typedef struct {
    bool enabled, has_depth, has_color, depth_test, depth_write, stencil, alpha_to_coverage, unknown;
    uint32_t samples;
} DepthNoFsState;

static inline bool depth_no_fs_eligible(const ShaderInfo *fs, const DepthNoFsState *s) {
    if (!s->enabled || !s->has_depth || s->has_color || !s->depth_test || !s->depth_write || s->stencil ||
        s->alpha_to_coverage || s->unknown || s->samples != 1 || !fs || !fs->depth_omit_safe) return false;
    // Recheck the public metadata: a new resource/coverage flag must not silently broaden the certificate.
    DepthProbeDraw d = {.fs = fs, .width = 1, .height = 1, .samples = s->samples, .has_depth = true};
    return depth_probe_exclusions(&d) == 0;
}
