// Measurement only: conservative fragment-elimination candidates, never a pipeline eligibility contract.
// Kept independent of Metal so synthetic tests exercise the same classification and bounded counters.
#pragma once
#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include "maxwell/shader.h"

enum {
    DP_DISCARD, DP_DEPTH_OUTPUT, DP_MEMORY, DP_MULTISAMPLE, DP_COVERAGE, DP_UNKNOWN, DP_GMEM_READ,
    DP_REASON_COUNT
};
static const char *const depth_probe_reasons[DP_REASON_COUNT] = {
    "discard", "depth_output", "memory", "msaa", "coverage", "unknown", "gmem_read"
};

typedef struct {
    const ShaderInfo *fs;
    uint32_t width, height, samples;  // actual depth attachment allocation (including its view's mip level)
    bool has_color, has_depth, alpha_to_coverage, unsupported;
} DepthProbeDraw;

// Reasons overlap: a draw with both discard and depth output increments both. Unknown metadata must never
// accidentally become a candidate. Global-memory reads are conservatively excluded separately from known writes.
static inline unsigned depth_probe_exclusions(const DepthProbeDraw *d) {
    unsigned bits = 0;
    if (d->samples > 1) bits |= 1u << DP_MULTISAMPLE;
    if (d->alpha_to_coverage) bits |= 1u << DP_COVERAGE;
    if (d->unsupported || !d->width || !d->height || !d->samples) bits |= 1u << DP_UNKNOWN;
    const ShaderInfo *s = d->fs;
    if (!s) return bits | (1u << DP_UNKNOWN);
    if (s->uses_discard) bits |= 1u << DP_DISCARD;
    if (s->writes_depth) bits |= 1u << DP_DEPTH_OUTPUT;
    if (s->writes_sample_mask) bits |= 1u << DP_COVERAGE;
    if (s->uses_gmem_store) bits |= 1u << DP_MEMORY;
    if (s->uses_gmem && !s->uses_gmem_store) bits |= 1u << DP_GMEM_READ;
    if (s->stage != STAGE_FRAGMENT || !s->msl || s->error[0] || s->ntex < 0 || s->ntex > 64 ||
        s->uses_gmem_map || s->writes_point_size || (s->cbuf_mask & ~0x3ffffu) || (s->cbuf_dynamic & ~0x3ffffu))
        bits |= 1u << DP_UNKNOWN;
    for (int i = 0; i < s->ntex && i < 64; i++) {
        if (s->tex[i].is_image) bits |= 1u << DP_MEMORY;  // metadata does not distinguish image reads from writes
        if (s->tex[i].bindless || s->tex[i].type > TEXTYPE_2D_MS) bits |= 1u << DP_UNKNOWN;
    }
    return bits;
}

typedef struct {
    uint64_t total, depth_only, eligible, excluded[DP_REASON_COUNT];
} DepthProbeCounts;
enum { DP_GROUPS = 8 };
typedef struct { uint32_t width, height; DepthProbeCounts counts; } DepthProbeGroup;
typedef struct {
    DepthProbeCounts counts;
    DepthProbeGroup groups[DP_GROUPS];
    int ngroups;
    DepthProbeCounts other;  // bounded storage even during a resize or with many mip levels
} DepthProbe;

static inline void depth_probe_count(DepthProbeCounts *c, bool depth_only, unsigned reasons) {
    c->total++;
    if (!depth_only) return;
    c->depth_only++;
    if (!reasons) c->eligible++;
    for (int i = 0; i < DP_REASON_COUNT; i++) if (reasons & (1u << i)) c->excluded[i]++;
}

static inline void depth_probe_note(DepthProbe *p, const DepthProbeDraw *d) {
    bool depth_only = d->has_depth && !d->has_color;
    unsigned reasons = depth_only ? depth_probe_exclusions(d) : 0;
    depth_probe_count(&p->counts, depth_only, reasons);
    if (!depth_only) return;
    DepthProbeCounts *group = &p->other;
    for (int i = 0; i <= p->ngroups; i++) {
        if (i == p->ngroups) {
            if (i == DP_GROUPS) break;
            p->groups[i].width = d->width;
            p->groups[i].height = d->height;
            p->ngroups++;
            group = &p->groups[i].counts;
            break;
        }
        if (p->groups[i].width == d->width && p->groups[i].height == d->height) {
            group = &p->groups[i].counts;
            break;
        }
    }
    depth_probe_count(group, true, reasons);
}

// One bounded line for a reporting interval or a target-size group. Counts, not GPU timings or pixel coverage.
static inline void depth_probe_format(char *out, size_t size, const DepthProbeCounts *c) {
    snprintf(out, size, "total=%" PRIu64 " depth_only=%" PRIu64 " potential=%" PRIu64
             " excluded(overlap): discard=%" PRIu64 " depth_output=%" PRIu64 " memory=%" PRIu64
             " msaa=%" PRIu64 " coverage=%" PRIu64 " unknown=%" PRIu64 " gmem_read=%" PRIu64,
             c->total, c->depth_only, c->eligible, c->excluded[DP_DISCARD], c->excluded[DP_DEPTH_OUTPUT],
             c->excluded[DP_MEMORY], c->excluded[DP_MULTISAMPLE], c->excluded[DP_COVERAGE],
             c->excluded[DP_UNKNOWN], c->excluded[DP_GMEM_READ]);
}
