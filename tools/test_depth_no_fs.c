// Synthetic metadata and Maxwell programs only; no game shader binaries.
#include <assert.h>
#include <stdio.h>
#include "../runtime/nvn/depth_no_fs.h"

static int cases;
#define CHECK(x) do { assert(x); cases++; } while (0)
#define HEADER (2u | (3u << 5) | (5u << 10))
#define EXIT UINT64_C(0xe30000000007000f)

static ShaderInfo *translate(uint32_t header, uint32_t outputs, uint64_t instruction, bool glsl, bool debug) {
    uint64_t blob[20] = {0};
    ((uint32_t *)blob)[0x30 / 4] = header;
    ((uint32_t *)blob)[0x78 / 4] = 15; // color outputs don't affect an unattached target
    ((uint32_t *)blob)[0x7c / 4] = outputs;
    blob[17] = instruction;
    blob[18] = EXIT;
    ShaderKey key = {.glsl = glsl};
    maxwell_dbg_code = debug ? (const uint8_t *)blob : NULL;
    maxwell_dbg_pc = 8;
    ShaderInfo *s = maxwell_translate((const uint8_t *)blob, 0x98, STAGE_FRAGMENT, &key);
    maxwell_dbg_code = NULL;
    return s;
}

int main(void) {
    ShaderInfo fs = {.stage = STAGE_FRAGMENT, .msl = "synthetic", .num_insts = 1};
    const ShaderInfo clean = fs;
    CHECK(depth_no_fs_certify(&fs, HEADER, 0, false));
    CHECK(!depth_no_fs_certify(NULL, HEADER, 0, false));
    CHECK(!depth_no_fs_certify(&fs, HEADER, 0, true));
    CHECK(!depth_no_fs_certify(&fs, 0, 0, false));
    CHECK(!depth_no_fs_certify(&fs, HEADER ^ 1u, 0, false));
    CHECK(!depth_no_fs_certify(&fs, HEADER ^ (1u << 5), 0, false));
    CHECK(!depth_no_fs_certify(&fs, HEADER ^ (1u << 10), 0, false));
    for (int i = 0; i < 32; i++) CHECK(!depth_no_fs_certify(&fs, HEADER, 1u << i, false));
    for (int i = 0; i < 32; i++) {
        if (((1u << 15) | (1u << 16) | (31u << 21) | (15u << 28)) & (1u << i))
            CHECK(!depth_no_fs_certify(&fs, HEADER | (1u << i), 0, false));
    }
    fs.num_insts = 0; CHECK(!depth_no_fs_certify(&fs, HEADER, 0, false)); fs = clean;

    fs.depth_omit_safe = true;
    const ShaderInfo certified = fs;
    DepthNoFsState state = {.enabled = true, .has_depth = true, .depth_test = true, .depth_write = true, .samples = 1};
    const DepthNoFsState good = state;
    CHECK(depth_no_fs_eligible(&fs, &state));
    CHECK(!depth_no_fs_eligible(NULL, &state));
#define STATE(field, value) state.field = value; CHECK(!depth_no_fs_eligible(&fs, &state)); state = good
    STATE(enabled, false); STATE(has_depth, false); STATE(has_color, true);
    STATE(depth_test, false); STATE(depth_write, false); STATE(stencil, true);
    STATE(alpha_to_coverage, true); STATE(unknown, true); STATE(samples, 0); STATE(samples, 2); STATE(samples, 4);
#undef STATE
#define META(field, value) fs.field = value; CHECK(!depth_no_fs_eligible(&fs, &state)); fs = certified
    META(depth_omit_safe, false); META(uses_discard, true); META(writes_depth, true);
    META(writes_sample_mask, true); META(uses_gmem_store, true); META(uses_gmem, true);
    META(uses_gmem_map, true); META(writes_point_size, true); META(stage, STAGE_VERTEX);
    META(msl, NULL); META(error[0], 'x'); META(ntex, -1); META(ntex, 65);
    META(cbuf_mask, 1u << 18); META(cbuf_dynamic, 1u << 18);
    fs.ntex = 1;
    META(tex[0].is_image, true);
    fs.ntex = 1; META(tex[0].bindless, true);
    fs.ntex = 1; META(tex[0].type, 255);
#undef META
    ShaderInfo *s = translate(HEADER, 0, EXIT, false, false);
    CHECK(s->msl && !s->error[0] && s->depth_omit_safe && depth_no_fs_eligible(s, &good));
    maxwell_free(s);
    s = translate(HEADER, 1, EXIT, false, false);
    CHECK(s->msl && s->writes_sample_mask && !s->depth_omit_safe); maxwell_free(s);
    s = translate(HEADER, 2, EXIT, false, false);
    CHECK(s->msl && s->writes_depth && !s->depth_omit_safe); maxwell_free(s);
    s = translate(HEADER, 4, EXIT, false, false);
    CHECK(s->msl && !s->depth_omit_safe); maxwell_free(s);
    s = translate(HEADER | (1u << 15), 0, EXIT, false, false);
    CHECK(s->msl && !s->depth_omit_safe); maxwell_free(s);
    s = translate(HEADER | (1u << 16), 0, EXIT, false, false);
    CHECK(s->msl && !s->depth_omit_safe); maxwell_free(s);
    s = translate(HEADER, 0, UINT64_C(0xe330000000070000), false, false); // KIL
    CHECK(s->msl && s->uses_discard && !s->depth_omit_safe); maxwell_free(s);
    for (int store = 0; store < 2; store++) {
        uint64_t op = (store ? UINT64_C(0xeed8000000000000) : UINT64_C(0xeed0000000000000)) |
                      (7ull << 16) | (255ull << 8) | (4ull << 48);
        s = translate(HEADER, 0, op, false, false); // STG/LDG (including MSL's unreported store flag)
        CHECK(s->msl && s->uses_gmem && !s->depth_omit_safe); maxwell_free(s);
    }
    s = translate(HEADER, 0, UINT64_C(0x1230000000070000), false, false);
    CHECK(s->error[0] && !s->depth_omit_safe); maxwell_free(s);
    s = translate(HEADER, 0, EXIT, true, false);
    CHECK(s->msl && !s->depth_omit_safe); maxwell_free(s);
    s = translate(HEADER, 0, EXIT, false, true);
    CHECK(s->msl && !s->depth_omit_safe); maxwell_free(s);
    printf("%d depth no-FS synthetic checks passed\n", cases);
    return 0;
}
