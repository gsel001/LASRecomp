// Synthetic metadata only: no Metal device, game shaders, assets or generated code.
#include <assert.h>
#include <stdio.h>
#include "../runtime/nvn/depth_probe.h"

static int cases;
static void check(DepthProbeDraw d, unsigned want) {
    ShaderInfo before = {0};
    if (d.fs) before = *d.fs;
    assert(depth_probe_exclusions(&d) == want);
    if (d.fs) assert(!memcmp(&before, d.fs, sizeof before));  // the metadata is read-only
    cases++;
}

int main(void) {
    ShaderInfo fs = {.stage = STAGE_FRAGMENT, .msl = "synthetic", .num_insts = 1};
    const ShaderInfo clean = fs;
    DepthProbeDraw d = {.fs = &fs, .width = 2048, .height = 2048, .samples = 1, .has_depth = true};
    check(d, 0);
    fs.uses_discard = true; check(d, 1u << DP_DISCARD); fs = clean;
    fs.writes_depth = true; check(d, 1u << DP_DEPTH_OUTPUT); fs = clean;
    fs.writes_sample_mask = true; check(d, 1u << DP_COVERAGE); fs = clean;
    fs.uses_gmem_store = fs.uses_gmem = true; check(d, 1u << DP_MEMORY); fs = clean;
    fs.uses_gmem = true; check(d, 1u << DP_GMEM_READ); fs = clean;
    fs.ntex = 1; fs.tex[0].is_image = true; check(d, 1u << DP_MEMORY); fs = clean;
    d.samples = 4; check(d, 1u << DP_MULTISAMPLE); d.samples = 1;
    d.alpha_to_coverage = true; check(d, 1u << DP_COVERAGE); d.alpha_to_coverage = false;
    d.fs = NULL; check(d, 1u << DP_UNKNOWN); d.fs = &fs;
    fs.msl = NULL; check(d, 1u << DP_UNKNOWN); fs = clean;
    fs.stage = STAGE_VERTEX; check(d, 1u << DP_UNKNOWN); fs = clean;
    fs.error[0] = 'x'; check(d, 1u << DP_UNKNOWN); fs = clean;
    fs.ntex = -1; check(d, 1u << DP_UNKNOWN); fs = clean;
    fs.ntex = 65; check(d, 1u << DP_UNKNOWN); fs = clean;
    fs.ntex = 1; fs.tex[0].type = 255; check(d, 1u << DP_UNKNOWN); fs = clean;
    fs.ntex = 1; fs.tex[0].bindless = true; check(d, 1u << DP_UNKNOWN); fs = clean;
    fs.uses_gmem_map = true; check(d, 1u << DP_UNKNOWN); fs = clean;
    fs.writes_point_size = true; check(d, 1u << DP_UNKNOWN); fs = clean;
    fs.cbuf_mask = 1u << 18; check(d, 1u << DP_UNKNOWN); fs = clean;
    fs.cbuf_dynamic = 1u << 18; check(d, 1u << DP_UNKNOWN); fs = clean;
    d.width = 0; check(d, 1u << DP_UNKNOWN); d.width = 2048;
    d.height = 0; check(d, 1u << DP_UNKNOWN); d.height = 2048;
    d.samples = 0; check(d, 1u << DP_UNKNOWN); d.samples = 1;
    d.unsupported = true; check(d, 1u << DP_UNKNOWN); d.unsupported = false;
    fs.uses_discard = fs.writes_depth = fs.uses_gmem_store = true;
    d.samples = 4; d.alpha_to_coverage = d.unsupported = true;
    unsigned combined = (1u << DP_DISCARD) | (1u << DP_DEPTH_OUTPUT) | (1u << DP_MEMORY) |
                        (1u << DP_MULTISAMPLE) | (1u << DP_COVERAGE) | (1u << DP_UNKNOWN);
    check(d, combined);

    DepthProbe p = {0};
    depth_probe_note(&p, &d);
    assert(p.counts.total == 1 && p.counts.depth_only == 1 && !p.counts.eligible);
    for (int i = 0; i < DP_REASON_COUNT; i++) assert(p.counts.excluded[i] == ((combined >> i) & 1));
    fs = clean; d.samples = 1; d.alpha_to_coverage = d.unsupported = false;
    depth_probe_note(&p, &d);
    assert(p.counts.total == 2 && p.counts.depth_only == 2 && p.counts.eligible == 1 && p.ngroups == 1);
    d.has_color = true; depth_probe_note(&p, &d);  // even a write-masked color attachment is outside this strict probe
    d.has_color = false; d.has_depth = false; depth_probe_note(&p, &d);
    assert(p.counts.total == 4 && p.counts.depth_only == 2 && p.groups[0].counts.total == 2);
    cases++;

    memset(&p, 0, sizeof p); d.has_depth = true;
    for (int i = 0; i < DP_GROUPS + 3; i++) { d.width = 32u << i; depth_probe_note(&p, &d); }
    assert(p.ngroups == DP_GROUPS && p.other.total == 3 && p.other.eligible == 3);
    d.width = 32; depth_probe_note(&p, &d);  // existing bucket still works after capacity is reached
    assert(p.groups[0].counts.total == 2);
    uint64_t sum = p.other.total;
    for (int i = 0; i < p.ngroups; i++) sum += p.groups[i].counts.total;
    assert(sum == p.counts.depth_only && sum == p.counts.eligible);
    cases++;

    char text[512], tiny[8];
    p.counts.total = UINT64_C(5000000000);
    depth_probe_format(text, sizeof text, &p.counts);
    assert(strstr(text, "total=5000000000 depth_only=12 potential=12"));
    assert(strstr(text, "excluded(overlap): discard=0"));
    depth_probe_format(tiny, sizeof tiny, &p.counts);
    assert(tiny[sizeof tiny - 1] == '\0');
    cases++;
    memset(&p, 0, sizeof p);
    assert(!p.counts.total && !p.ngroups && !p.other.total);
    depth_probe_note(&p, &d);
    assert(p.counts.total == 1 && p.ngroups == 1 && p.groups[0].counts.eligible == 1);
    cases++;
    printf("%d depth probe synthetic cases passed\n", cases);
    return 0;
}
