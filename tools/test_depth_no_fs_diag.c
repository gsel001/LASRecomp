// Synthetic accounting and observer equivalence; never loads a game or creates a Metal device.
#include <assert.h>
#include <stdio.h>
#include "../runtime/nvn/depth_no_fs_diag.h"

static unsigned checks;
#define CHECK(x) do { assert(x); checks++; } while (0)
#define HEADER (2u | (3u << 5) | (5u << 10))

int main(void) {
    ShaderInfo fs = {.stage = STAGE_FRAGMENT, .msl = "synthetic", .num_insts = 1, .depth_omit_safe = true};
    const ShaderInfo clean = fs;
    CHECK(depth_no_fs_diag_certify(&fs, HEADER, 0, false) == 0);
    for (int bit = 0; bit < 32; bit++) {
        uint32_t header = HEADER ^ (1u << bit);
        CHECK(depth_no_fs_certify(&fs, header, 0, false) == (depth_no_fs_diag_certify(&fs, header, 0, false) == 0));
        CHECK(!depth_no_fs_certify(&fs, HEADER, 1u << bit, false));
        CHECK(depth_no_fs_diag_certify(&fs, HEADER, 1u << bit, false) != 0);
    }
    CHECK(depth_no_fs_diag_certify(NULL, HEADER, 0, false) == DND_BIT(DND_SHADER_MISSING));
    CHECK(depth_no_fs_diag_certify(&fs, HEADER, 0, true) == DND_BIT(DND_CERT_DEBUG));
#define METADATA(field, value, reason) \
    fs.field = value; CHECK(depth_no_fs_diag_certify(&fs, HEADER, 0, false) & DND_BIT(reason)); \
    CHECK(!depth_no_fs_certify(&fs, HEADER, 0, false)); fs = clean
    METADATA(uses_discard, true, DND_DISCARD);
    METADATA(writes_depth, true, DND_DEPTH_OUTPUT);
    METADATA(writes_sample_mask, true, DND_COVERAGE);
    METADATA(uses_gmem_store, true, DND_GMEM_WRITE);
    METADATA(uses_gmem, true, DND_GMEM_READ);
    METADATA(uses_gmem_map, true, DND_OTHER_EFFECT);
    METADATA(writes_point_size, true, DND_OTHER_EFFECT);
    METADATA(ntex, 65, DND_SHADER_UNKNOWN);
    METADATA(msl, NULL, DND_SHADER_UNKNOWN);
    METADATA(num_insts, 0, DND_CERT_EMPTY);
    fs.ntex = 1; METADATA(tex[0].is_image, true, DND_IMAGE_RESOURCE);
    fs.ntex = 1; METADATA(tex[0].bindless, true, DND_SHADER_UNKNOWN);
    strcpy(fs.error, "unknown instruction (synthetic)");
    CHECK(depth_no_fs_diag_first(depth_no_fs_diag_certify(&fs, HEADER, 0, false)) == DND_INSTRUCTION_UNKNOWN);
    fs = clean;
#undef METADATA

    // Every combination of the live guards, including the unknown subconditions: observing them must never
    // disagree with the unchanged production helper or mutate any input. Both sparse color slots and views tested.
    for (unsigned mask = 0; mask < (1u << 15); mask++) for (int samples = 0; samples < 3; samples++) {
        DepthNoFsDiagState s = {0};
#define B(i) ((mask & (1u << (i))) != 0)
        s.live.enabled = B(0); s.depth_present = B(1); s.depth_format = B(2);
        s.live.has_depth = s.depth_present && s.depth_format;
        s.live.has_color = B(3); s.live.depth_test = B(4); s.live.depth_write = B(5);
        s.live.stencil = B(6); s.live.alpha_to_coverage = B(7);
        s.target = B(8); s.view = B(9); s.color_declared = B(10); s.compare = B(11);
        s.depth_env = B(12); s.images = B(13); s.topology = B(14);
        s.live.unknown = !s.depth_present || s.target || s.view || s.color_declared || s.compare || s.depth_env || s.images || s.topology;
        s.live.samples = samples == 2 ? 4 : samples;
        DepthNoFsDiagState before = s;
        CHECK((depth_no_fs_diag_rejections(&fs, &s) == 0) == depth_no_fs_eligible(&fs, &s.live));
        CHECK(!memcmp(&fs, &clean, sizeof fs) && !memcmp(&s, &before, sizeof s));
#undef B
    }
    DepthNoFsDiagState s = {.live = {.enabled = true, .has_depth = true, .depth_test = true, .depth_write = true, .samples = 1},
                           .depth_present = true, .depth_format = true};
    fs.depth_omit_safe = false;
    CHECK(depth_no_fs_diag_rejections(&fs, &s) == DND_BIT(DND_CERT_UNAVAILABLE));
    fs.depth_omit_rejections = DND_BIT(DND_CERT_VERSION);
    CHECK(depth_no_fs_diag_rejections(&fs, &s) == DND_BIT(DND_CERT_VERSION));
    fs = clean;
    s.color_declared = s.live.unknown = true;
    CHECK(depth_no_fs_diag_rejections(&fs, &s) == DND_BIT(DND_COLOR_DECLARED));
    s.color_declared = s.live.unknown = false; s.view = s.live.unknown = true;
    CHECK(depth_no_fs_diag_rejections(&fs, &s) == DND_BIT(DND_VIEW));

    DepthNoFsDiag p = {0};
    DepthNoFsDiagDecision d = {.depth = true, .depth_only = true, .potential = true, .certified = true, .entered = true, .eligible = true};
    depth_no_fs_diag_complete(&p, &d, true); // experimental pipeline used
    depth_no_fs_diag_complete(&p, &d, false); // eligible, pipeline fallback
    d.eligible = false; d.reasons = DND_BIT(DND_STENCIL) | DND_BIT(DND_VIEW) | DND_BIT(DND_COLOR_DECLARED);
    d.raw0_metal1 = true;
    depth_no_fs_diag_complete(&p, &d, false);
    d.depth = d.depth_only = d.potential = false; d.reasons = DND_BIT(DND_COLOR_BOUND);
    depth_no_fs_diag_complete(&p, &d, false);
    CHECK(p.total == 4 && p.depth == 3 && p.depth_only == 3 && p.potential == 3 && p.eligible == 2 && p.omitted == 1);
    CHECK(p.raw0_metal1 == 1 && p.potential_raw0_metal1 == 1);
    CHECK(p.rejected[DND_STENCIL] == 1 && p.rejected[DND_COLOR_BOUND] == 1 && p.rejected[DND_VIEW] == 0);
    CHECK(p.potential_rejected[DND_STENCIL] == 1 && p.potential_rejected[DND_COLOR_BOUND] == 0);
    CHECK(p.overlap[DND_STENCIL] == 1 && p.overlap[DND_VIEW] == 1 && p.overlap[DND_COLOR_DECLARED] == 1);
    uint64_t rejected = 0;
    for (int i = 1; i < DND_COUNT; i++) rejected += p.rejected[i];
    CHECK(p.total == p.eligible + rejected && !p.inconsistent);
    // A drift between observer and actual selector is surfaced, not used to overrule the selector.
    d.reasons = 0; depth_no_fs_diag_complete(&p, &d, false);
    CHECK(p.inconsistent == 1 && p.rejected[DND_INCONSISTENT] == 1);
    d.eligible = true; d.reasons = DND_BIT(DND_STENCIL); depth_no_fs_diag_complete(&p, &d, true);
    CHECK(p.inconsistent == 2 && p.eligible == 3 && p.omitted == 2);
    DepthNoFsDiag baseline = {0};
    DepthNoFsDiagDecision safe_off = {.depth = true, .depth_only = true, .potential = true,
        .view_equivalent = true, .safe_without_switch = true, .reasons = DND_BIT(DND_DISABLED)};
    depth_no_fs_diag_complete(&baseline, &safe_off, false);
    CHECK(baseline.potential_view_equivalent == 1 && baseline.potential_safe == 1 && !baseline.eligible && !baseline.omitted);
    uint64_t counts[DND_COUNT] = {0}; char text[1800], tiny[8];
    depth_no_fs_diag_format(text, sizeof text, counts); CHECK(!strcmp(text, "none"));
    counts[DND_COLOR_DECLARED] = UINT64_C(5000000000); counts[DND_CERT_VERSION] = 9;
    depth_no_fs_diag_format(text, sizeof text, counts);
    CHECK(!strcmp(text, "color_declared=5000000000 cert_version=9"));
    depth_no_fs_diag_format(tiny, sizeof tiny, counts); CHECK(tiny[sizeof tiny - 1] == 0);
    depth_no_fs_diag_format(NULL, 0, counts);
    printf("%u depth no-FS diagnostic checks passed (98,304 guard combinations)\n", checks);
    return 0;
}
