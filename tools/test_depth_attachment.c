// Synthetic NVN metadata and actual-attachment witnesses only; no assets or GPU needed.
#include <assert.h>
#include "../runtime/nvn/depth_attachment.h"
#include "../runtime/nvn/depth_no_fs.h"

static unsigned checks;
#define CHECK(x) do { assert(x); checks++; } while (0)
int main(void) {
    NvnTexture t = {.target = 1, .format = 0x35, .levels = 3, .swizzle = {2,3,4,5}};
    NvnTextureView v = {.num_levels = 3, .num_layers = 1, .format = 0x35, .target = 1, .swizzle = {2,3,4,5}};
    DepthAttachment a = {.width = 64, .height = 32, .levels = 3, .layers = 1, .samples = 1,
                         .base_2d = true, .attached_is_base = true, .format_matches = true, .subresource_zero = true};
    const NvnTexture clean_t = t;
    const NvnTextureView clean_v = v;
    const DepthAttachment clean_a = a;
    const uint32_t samples[] = {0,1,2,4,8,UINT32_MAX};
    for (unsigned r = 0; r < 6; r++) for (unsigned actual = 0; actual < 6; actual++) for (unsigned pipeline = 0; pipeline < 6; pipeline++)
        CHECK((depth_attachment_samples(samples[r], samples[actual], samples[pipeline]) == 1) ==
              (samples[r] <= 1 && samples[actual] == 1 && samples[pipeline] == 1));
    for (unsigned mask = 0; mask < 64; mask++) {
        v.setmask = mask;
        CHECK(depth_attachment_view(&t, &v, true, &a));
    }
    v = clean_v;
    CHECK(depth_attachment_view(&t, NULL, false, &a));
    CHECK(!depth_attachment_view(&t, NULL, true, &a));
    CHECK(!depth_attachment_view(NULL, &v, true, &a));
    CHECK(!depth_attachment_view(&t, &v, true, NULL));
    for (int bit = 6; bit < 32; bit++) { v.setmask = 1u << bit; CHECK(!depth_attachment_view(&t, &v, true, &a)); }
#define VIEW(mask, field, value) v = clean_v; v.setmask = mask; v.field = value; CHECK(!depth_attachment_view(&t, &v, true, &a))
    VIEW(1, base_level, 1); VIEW(1, num_levels, 1); VIEW(1, num_levels, 4); VIEW(1, num_levels, UINT16_MAX);
    VIEW(2, min_layer, 1); VIEW(2, num_layers, 2); VIEW(2, num_layers, UINT16_MAX);
    VIEW(4, format, 0x33); VIEW(8, swizzle[0], 0); VIEW(16, ds_mode, 1); VIEW(32, target, 4);
#undef VIEW
    v = clean_v; v.setmask = 3; v.num_levels = v.num_layers = 0;
    CHECK(depth_attachment_view(&t, &v, true, &a)); // zero counts mean the full remaining range
    memset(&v, 0xff, sizeof v); v.setmask = 0;
    CHECK(depth_attachment_view(&t, &v, true, &a)); // unset fields are ignored, exactly as view_texture
    v = clean_v;
#define ACTUAL(field, value) a = clean_a; a.field = value; CHECK(!depth_attachment_view(&t, &v, true, &a))
    ACTUAL(width, 0); ACTUAL(height, 0); ACTUAL(levels, 0); ACTUAL(layers, 0); ACTUAL(layers, 2);
    ACTUAL(base_2d, false); ACTUAL(attached_is_base, false); ACTUAL(format_matches, false); ACTUAL(subresource_zero, false);
#undef ACTUAL
    a = clean_a; t.target = 4; CHECK(!depth_attachment_view(&t, &v, true, &a)); t = clean_t;
    ShaderInfo fs = {.stage = STAGE_FRAGMENT, .msl = "synthetic", .num_insts = 1, .depth_omit_safe = true};
    DepthNoFsState state = {.enabled = true, .has_depth = true, .depth_test = true, .depth_write = true};
    for (unsigned raw = 0; raw <= 1; raw++) {
        t.samples = raw; v = clean_v; v.setmask = 63;
        state.samples = depth_attachment_samples(t.samples, a.samples, 1);
        state.unknown = !depth_attachment_view(&t, &v, true, &a);
        CHECK(depth_no_fs_eligible(&fs, &state));
        state.enabled = false; CHECK(!depth_no_fs_eligible(&fs, &state)); state.enabled = true;
        state.stencil = true; CHECK(!depth_no_fs_eligible(&fs, &state)); state.stencil = false;
        state.depth_write = false; CHECK(!depth_no_fs_eligible(&fs, &state)); state.depth_write = true;
        fs.uses_discard = true; CHECK(!depth_no_fs_eligible(&fs, &state)); fs.uses_discard = false;
        fs.writes_depth = true; CHECK(!depth_no_fs_eligible(&fs, &state)); fs.writes_depth = false;
        fs.writes_sample_mask = true; CHECK(!depth_no_fs_eligible(&fs, &state)); fs.writes_sample_mask = false;
        fs.uses_gmem = true; CHECK(!depth_no_fs_eligible(&fs, &state)); fs.uses_gmem = false;
        fs.depth_omit_safe = false; CHECK(!depth_no_fs_eligible(&fs, &state)); fs.depth_omit_safe = true;
    }
    CHECK(!memcmp(&a, &clean_a, sizeof a));
    printf("%u depth attachment checks passed\n", checks);
    return 0;
}
