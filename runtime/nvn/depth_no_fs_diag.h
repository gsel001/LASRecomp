// Observation only. These helpers never authorize a pipeline or alter the production eligibility contract.
#pragma once
#include "depth_no_fs.h"

enum {
    DND_PASS, DND_DISABLED, DND_DEPTH_MISSING, DND_DEPTH_FORMAT, DND_COLOR_BOUND,
    DND_DEPTH_TEST, DND_DEPTH_WRITE, DND_STENCIL, DND_A2C, DND_TARGET, DND_VIEW,
    DND_COLOR_DECLARED, DND_COMPARE, DND_DEPTH_ENV, DND_IMAGE_BOUND, DND_TOPOLOGY,
    DND_SAMPLES_UNKNOWN, DND_MSAA, DND_SHADER_MISSING, DND_INSTRUCTION_UNKNOWN, DND_SHADER_UNKNOWN,
    DND_DISCARD, DND_DEPTH_OUTPUT, DND_COVERAGE, DND_GMEM_WRITE, DND_GMEM_READ,
    DND_IMAGE_RESOURCE, DND_OTHER_EFFECT, DND_CERT_DEBUG, DND_CERT_EMPTY, DND_CERT_OUTPUT_RESERVED,
    DND_CERT_TYPE, DND_CERT_VERSION, DND_CERT_STAGE, DND_CERT_KILL, DND_CERT_STORE,
    DND_CERT_RESERVED, DND_CERT_STREAM, DND_CERT_UNAVAILABLE, DND_STATE_UNKNOWN, DND_INCONSISTENT,
    DND_COUNT
};
static const char *const depth_no_fs_diag_names[DND_COUNT] = {
    "pass", "switch_off", "depth_missing", "depth_format", "color_bound",
    "depth_test_off", "depth_write_off", "stencil", "alpha_to_coverage", "depth_target", "depth_view",
    "color_declared", "depth_compare", "depth_test_env_off", "image_bound", "topology",
    "samples_unknown", "msaa", "shader_missing", "instruction_unknown", "shader_unknown",
    "discard", "depth_output", "coverage", "gmem_write", "gmem_read_or_untyped",
    "image_resource", "other_shader_effect", "cert_debug", "cert_empty", "cert_output_reserved",
    "cert_type", "cert_version", "cert_stage", "cert_kill_header", "cert_store_header",
    "cert_reserved", "cert_stream", "cert_unavailable", "state_unknown", "inconsistent"
};
#define DND_BIT(reason) (UINT64_C(1) << (reason))

static inline uint64_t depth_no_fs_diag_metadata(const ShaderInfo *fs) {
    if (!fs) return DND_BIT(DND_SHADER_MISSING);
    uint64_t reasons = 0;
    DepthProbeDraw d = {.fs = fs, .width = 1, .height = 1, .samples = 1, .has_depth = true};
    unsigned probe = depth_probe_exclusions(&d);
    if (probe & (1u << DP_UNKNOWN)) reasons |= DND_BIT(DND_SHADER_UNKNOWN);
    if (fs->error[0] && (strstr(fs->error, "unsupported") || strstr(fs->error, "unknown")))
        reasons |= DND_BIT(DND_INSTRUCTION_UNKNOWN);
    if (probe & (1u << DP_DISCARD)) reasons |= DND_BIT(DND_DISCARD);
    if (probe & (1u << DP_DEPTH_OUTPUT)) reasons |= DND_BIT(DND_DEPTH_OUTPUT);
    if (probe & (1u << DP_COVERAGE)) reasons |= DND_BIT(DND_COVERAGE);
    if (fs->uses_gmem_store) reasons |= DND_BIT(DND_GMEM_WRITE);
    if (probe & (1u << DP_GMEM_READ)) reasons |= DND_BIT(DND_GMEM_READ);
    for (int i = 0; i < fs->ntex && i < 64; i++)
        if (fs->tex[i].is_image) reasons |= DND_BIT(DND_IMAGE_RESOURCE);
    if (fs->uses_gmem_map || fs->writes_point_size) reasons |= DND_BIT(DND_OTHER_EFFECT);
    return reasons;
}

// Diagnostic explanation of the existing certificate, recorded once during translation. No shader text is logged.
static inline uint64_t depth_no_fs_diag_certify(const ShaderInfo *fs, uint32_t header, uint32_t outputs, bool debug) {
    uint64_t reasons = depth_no_fs_diag_metadata(fs);
    if (!fs) return reasons;
    if (debug) reasons |= DND_BIT(DND_CERT_DEBUG);
    if (!fs->num_insts) reasons |= DND_BIT(DND_CERT_EMPTY);
    if (outputs & 1u) reasons |= DND_BIT(DND_COVERAGE);
    if (outputs & 2u) reasons |= DND_BIT(DND_DEPTH_OUTPUT);
    if (outputs & ~3u) reasons |= DND_BIT(DND_CERT_OUTPUT_RESERVED);
    if ((header & 31u) != 2) reasons |= DND_BIT(DND_CERT_TYPE);
    if (((header >> 5) & 31u) != 3) reasons |= DND_BIT(DND_CERT_VERSION);
    if (((header >> 10) & 15u) != 5) reasons |= DND_BIT(DND_CERT_STAGE);
    if (header & (1u << 15)) reasons |= DND_BIT(DND_CERT_KILL);
    if (header & (1u << 16)) reasons |= DND_BIT(DND_CERT_STORE);
    if (header & (31u << 21)) reasons |= DND_BIT(DND_CERT_RESERVED);
    if (header & (15u << 28)) reasons |= DND_BIT(DND_CERT_STREAM);
    return reasons;
}

typedef struct {
    DepthNoFsState live;
    bool depth_present, depth_format, target, view, color_declared, compare, depth_env, images, topology;
} DepthNoFsDiagState;

static inline uint64_t depth_no_fs_diag_rejections(const ShaderInfo *fs, const DepthNoFsDiagState *s) {
    uint64_t reasons = 0;
    if (!s->live.enabled) reasons |= DND_BIT(DND_DISABLED);
    if (!s->depth_present) reasons |= DND_BIT(DND_DEPTH_MISSING);
    else if (!s->depth_format) reasons |= DND_BIT(DND_DEPTH_FORMAT);
    if (s->live.has_color) reasons |= DND_BIT(DND_COLOR_BOUND);
    if (!s->live.depth_test) reasons |= DND_BIT(DND_DEPTH_TEST);
    if (!s->live.depth_write) reasons |= DND_BIT(DND_DEPTH_WRITE);
    if (s->live.stencil) reasons |= DND_BIT(DND_STENCIL);
    if (s->live.alpha_to_coverage) reasons |= DND_BIT(DND_A2C);
    if (s->target) reasons |= DND_BIT(DND_TARGET);
    if (s->view) reasons |= DND_BIT(DND_VIEW);
    if (s->color_declared) reasons |= DND_BIT(DND_COLOR_DECLARED);
    if (s->compare) reasons |= DND_BIT(DND_COMPARE);
    if (s->depth_env) reasons |= DND_BIT(DND_DEPTH_ENV);
    if (s->images) reasons |= DND_BIT(DND_IMAGE_BOUND);
    if (s->topology) reasons |= DND_BIT(DND_TOPOLOGY);
    if (s->live.unknown && !(s->target || s->view || s->color_declared || s->compare || s->depth_env ||
                            s->images || s->topology || !s->depth_present)) reasons |= DND_BIT(DND_STATE_UNKNOWN);
    if (!s->live.samples) reasons |= DND_BIT(DND_SAMPLES_UNKNOWN);
    else if (s->live.samples != 1) reasons |= DND_BIT(DND_MSAA);
    reasons |= depth_no_fs_diag_metadata(fs);
    if (fs && !fs->depth_omit_safe)
        reasons |= fs->depth_omit_rejections ? fs->depth_omit_rejections : DND_BIT(DND_CERT_UNAVAILABLE);
    return reasons;
}

typedef struct {
    uint64_t reasons;
    bool depth, depth_only, potential, certified, entered, eligible, raw0_metal1, view_equivalent, safe_without_switch;
} DepthNoFsDiagDecision;

typedef struct {
    uint64_t attempts, evaluated, eligible_evaluated, total, depth, depth_only, potential, certified, entered, eligible, omitted;
    uint64_t rejected[DND_COUNT], potential_rejected[DND_COUNT], overlap[DND_COUNT];
    uint64_t pending, failed, fallback, inconsistent;
    uint64_t pre_no_program, pre_program, pre_other, pre_missing_fs, pre_unknown_instruction;
    uint64_t post_pipeline, post_other;
    uint64_t raw0_metal1, potential_raw0_metal1;
    uint64_t potential_view_equivalent, potential_safe;
} DepthNoFsDiag;

static inline int depth_no_fs_diag_first(uint64_t reasons) {
    return reasons ? __builtin_ctzll(reasons) : DND_PASS;
}

static inline void depth_no_fs_diag_complete(DepthNoFsDiag *p, const DepthNoFsDiagDecision *d, bool omitted) {
    p->total++; p->depth += d->depth; p->depth_only += d->depth_only; p->potential += d->potential;
    p->certified += d->certified; p->entered += d->entered; p->eligible += d->eligible; p->omitted += omitted;
    p->raw0_metal1 += d->depth_only && d->raw0_metal1;
    p->potential_raw0_metal1 += d->potential && d->raw0_metal1;
    p->potential_view_equivalent += d->potential && d->view_equivalent;
    p->potential_safe += d->potential && d->safe_without_switch;
    bool mismatch = d->eligible != (d->reasons == 0) || (omitted && !d->eligible);
    p->inconsistent += mismatch;
    int first = d->eligible ? DND_PASS : d->reasons ? depth_no_fs_diag_first(d->reasons) : DND_INCONSISTENT;
    if (first) p->rejected[first]++;
    if (d->potential && first) p->potential_rejected[first]++;
    if (d->depth_only) {
        uint64_t reasons = d->reasons;
        while (reasons) { int i = __builtin_ctzll(reasons); p->overlap[i]++; reasons &= reasons - 1; }
    }
}

static inline void depth_no_fs_diag_format(char *out, size_t size, const uint64_t *counts) {
    size_t used = 0;
    if (!size) return;
    out[0] = 0;
    for (int i = 1; i < DND_COUNT && used < size - 1; i++) {
        if (!counts[i]) continue;
        int n = snprintf(out + used, size - used, "%s%s=%" PRIu64, used ? " " : "", depth_no_fs_diag_names[i], counts[i]);
        if (n < 0 || (size_t)n >= size - used) break;
        used += (size_t)n;
    }
    if (!used && !out[0]) snprintf(out, size, "none");
}
