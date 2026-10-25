// Standalone synthetic Metal regression: no window, game library, shaders, assets or saves.
#import <Metal/Metal.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../runtime/nvn/depth_attachment.h"
#include "../runtime/nvn/depth_no_fs.h"

int main(void) { @autoreleasepool {
    id<MTLDevice> device = MTLCreateSystemDefaultDevice();
    if (!device) { fprintf(stderr, "SKIP: no Metal device\n"); return 77; }
    NSError *error = nil;
    NSString *source = @"#include <metal_stdlib>\nusing namespace metal;\n"
        "struct V { float4 p [[position, invariant]]; };\n"
        "vertex V vs(uint i [[vertex_id]], constant float &z [[buffer(0)]]) {"
        " float2 p[3] = {float2(-1,-1),float2(3,-1),float2(-1,3)};"
        " return V{float4(p[i],z + p[i].x*0.05f + p[i].y*0.03f,1)}; }\n"
        "fragment float4 fs() { return float4(0.2,0.4,0.6,1); }\n";
    id<MTLLibrary> library = [device newLibraryWithSource:source options:nil error:&error];
    if (!library) { fprintf(stderr, "%s\n", error.localizedDescription.UTF8String); return 1; }
    id<MTLCommandQueue> queue = [device newCommandQueue];
    int tests = 0;
    for (int kind = 0; kind < 3; kind++) {
        bool combined = kind == 2;
        MTLPixelFormat format = kind == 0 ? MTLPixelFormatDepth16Unorm : kind == 1 ? MTLPixelFormatDepth32Float : MTLPixelFormatDepth32Float_Stencil8;
        for (int raw = 0; raw <= 1; raw++) for (int view = 0; view < 4; view++) {
        NSUInteger levels = view >= 2 ? 3 : 1;
        for (MTLCompareFunction comparison = MTLCompareFunctionNever; comparison <= MTLCompareFunctionAlways; comparison++) {
            for (int bias = 0; bias < 2; bias++) {
                id<MTLBuffer> depth[2], stencil[2];
                for (int omit = 0; omit < 2; omit++) {
                    MTLRenderPipelineDescriptor *pipeline = [MTLRenderPipelineDescriptor new];
                    pipeline.vertexFunction = [library newFunctionWithName:@"vs"];
                    pipeline.depthAttachmentPixelFormat = format;
                    if (combined) pipeline.stencilAttachmentPixelFormat = format;
                    MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:format
                                                          width:16 height:16 mipmapped:NO];
                    td.usage = MTLTextureUsageRenderTarget;
                    td.storageMode = MTLStorageModePrivate;
                    td.mipmapLevelCount = levels;
                    id<MTLTexture> target = [device newTextureWithDescriptor:td];
                    assert(target);
                    MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor new];
                    pass.depthAttachment.texture = target;
                    pass.depthAttachment.loadAction = MTLLoadActionClear;
                    pass.depthAttachment.storeAction = MTLStoreActionStore;
                    pass.depthAttachment.clearDepth = 0.5;
                    if (combined) {
                        pass.stencilAttachment.texture = target;
                        pass.stencilAttachment.loadAction = MTLLoadActionClear;
                        pass.stencilAttachment.storeAction = MTLStoreActionStore;
                        pass.stencilAttachment.clearStencil = 7;
                    }
                    NvnTexture texture = {.target = 1, .format = kind == 0 ? 0x32 : kind == 1 ? 0x33 : 0x35,
                        .samples = raw, .levels = (uint32_t)levels, .swizzle = {2,3,4,5}};
                    NvnTextureView nv = {.setmask = view >= 2 ? 63 : 0, .num_levels = view == 3 ? 0 : (uint16_t)levels,
                        .num_layers = view == 3 ? 0 : 1, .format = texture.format, .target = 1, .swizzle = {2,3,4,5}};
                    DepthAttachment observed = depth_attachment_observe(target, pass, format);
                    ShaderInfo fs = {.stage = STAGE_FRAGMENT, .msl = "synthetic", .num_insts = 1, .depth_omit_safe = true};
                    DepthNoFsState eligibility = {.enabled = omit != 0, .has_depth = true, .depth_test = true, .depth_write = true,
                        .samples = depth_attachment_samples(raw, observed.samples, (uint32_t)pipeline.rasterSampleCount),
                        .unknown = !depth_attachment_view(&texture, &nv, view != 0, &observed)};
                    bool selected = depth_no_fs_eligible(&fs, &eligibility);
                    assert(selected == (omit != 0)); // default keeps FS, experiment admits only the proven raw/view cases
                    pipeline.fragmentFunction = selected ? nil : [library newFunctionWithName:@"fs"];
                    id<MTLRenderPipelineState> state = [device newRenderPipelineStateWithDescriptor:pipeline error:&error];
                    if (!state) { fprintf(stderr, "%s\n", error.localizedDescription.UTF8String); return 1; }
                    // Negative real-Metal witnesses: shifted attachment levels, distinct texture views and
                    // mismatched formats cannot be certified even if other metadata looks benign.
                    DepthAttachment invalid = depth_attachment_observe(target, pass, MTLPixelFormatInvalid);
                    assert(!depth_attachment_view(&texture, &nv, view != 0, &invalid));
                    if (levels > 1) {
                        pass.depthAttachment.level = 1;
                        invalid = depth_attachment_observe(target, pass, format);
                        assert(!depth_attachment_view(&texture, &nv, view != 0, &invalid));
                        pass.depthAttachment.level = 0;
                        id<MTLTexture> subset = [target newTextureViewWithPixelFormat:format textureType:MTLTextureType2D
                            levels:NSMakeRange(1,1) slices:NSMakeRange(0,1)];
                        assert(subset);
                        pass.depthAttachment.texture = subset;
                        invalid = depth_attachment_observe(target, pass, format);
                        assert(!depth_attachment_view(&texture, &nv, view != 0, &invalid));
                        pass.depthAttachment.texture = target;
                    }
                    MTLDepthStencilDescriptor *ds = [MTLDepthStencilDescriptor new];
                    ds.depthCompareFunction = comparison;
                    ds.depthWriteEnabled = YES; // stencil stays disabled, as required by the experiment
                    id<MTLCommandBuffer> command = [queue commandBuffer];
                    // Sentinels in untouched mip levels prove the admitted full-range view still writes mip zero only.
                    for (NSUInteger level = 1; level < levels; level++) {
                        MTLRenderPassDescriptor *clear = [MTLRenderPassDescriptor new];
                        clear.depthAttachment.texture = target; clear.depthAttachment.level = level;
                        clear.depthAttachment.loadAction = MTLLoadActionClear; clear.depthAttachment.storeAction = MTLStoreActionStore;
                        clear.depthAttachment.clearDepth = 0.875;
                        if (combined) {
                            clear.stencilAttachment.texture = target; clear.stencilAttachment.level = level;
                            clear.stencilAttachment.loadAction = MTLLoadActionClear; clear.stencilAttachment.storeAction = MTLStoreActionStore;
                            clear.stencilAttachment.clearStencil = 3;
                        }
                        [[command renderCommandEncoderWithDescriptor:clear] endEncoding];
                    }
                    id<MTLRenderCommandEncoder> encoder = [command renderCommandEncoderWithDescriptor:pass];
                    [encoder setRenderPipelineState:state];
                    [encoder setDepthStencilState:[device newDepthStencilStateWithDescriptor:ds]];
                    if (bias) [encoder setDepthBias:-2 slopeScale:-1 clamp:0];
                    [encoder setScissorRect:(MTLScissorRect){2, 3, 10, 9}];
                    // In front, behind, and exactly equal to the existing depth. Includes EQUAL decal pre-passes.
                    for (int draw = 0; draw < 3; draw++) {
                        float z = draw == 0 ? 0.25f : draw == 1 ? 0.75f : 0.5f;
                        [encoder setVertexBytes:&z length:sizeof z atIndex:0];
                        [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
                    }
                    [encoder endEncoding];
                    depth[omit] = [device newBufferWithLength:4096 * levels options:MTLResourceStorageModeShared];
                    stencil[omit] = [device newBufferWithLength:4096 * levels options:MTLResourceStorageModeShared];
                    id<MTLBlitCommandEncoder> blit = [command blitCommandEncoder];
                    for (NSUInteger level = 0; level < levels; level++) {
                    [blit copyFromTexture:target sourceSlice:0 sourceLevel:level sourceOrigin:(MTLOrigin){0,0,0}
                               sourceSize:(MTLSize){16 >> level,16 >> level,1} toBuffer:depth[omit] destinationOffset:4096 * level
                     destinationBytesPerRow:256 destinationBytesPerImage:4096
                                   options:combined ? MTLBlitOptionDepthFromDepthStencil : MTLBlitOptionNone];
                    if (combined)
                        [blit copyFromTexture:target sourceSlice:0 sourceLevel:level sourceOrigin:(MTLOrigin){0,0,0}
                                   sourceSize:(MTLSize){16 >> level,16 >> level,1} toBuffer:stencil[omit] destinationOffset:4096 * level
                         destinationBytesPerRow:256 destinationBytesPerImage:4096 options:MTLBlitOptionStencilFromDepthStencil];
                    }
                    [blit endEncoding];
                    [command commit];
                    [command waitUntilCompleted];
                    if (command.status != MTLCommandBufferStatusCompleted) {
                        fprintf(stderr, "%s\n", command.error.localizedDescription.UTF8String); return 1;
                    }
                }
                for (NSUInteger level = 0; level < levels; level++) for (int y = 0; y < (16 >> level); y++) {
                    const unsigned char *a = depth[0].contents, *b = depth[1].contents;
                    size_t offset = 4096 * level + y * 256;
                    assert(!memcmp(a + offset, b + offset, (16 >> level) * (kind == 0 ? 2 : sizeof(float))));
                    if (level) {
                        if (kind == 0) assert(*(const uint16_t *)(b + offset) >= 57343 && *(const uint16_t *)(b + offset) <= 57344);
                        else assert(*(const float *)(b + offset) == 0.875f);
                    }
                    if (combined) {
                        a = stencil[0].contents; b = stencil[1].contents;
                        assert(!memcmp(a + offset, b + offset, 16 >> level));
                        for (int x = 0; x < (16 >> level); x++) assert(b[offset + x] == (level ? 3 : 7));
                    }
                }
                // Verify the readback actually contains the clear value outside the scissor.
                if (kind == 0) assert(*(const uint16_t *)depth[0].contents >= 32767 && *(const uint16_t *)depth[0].contents <= 32768);
                else assert(*(const float *)depth[0].contents == 0.5f);
                if (comparison == MTLCompareFunctionLess && !bias) {
                    if (kind == 0) assert(*(const uint16_t *)((const unsigned char *)depth[0].contents + 5 * 256 + 5 * 2) < 32767);
                    else assert(*(const float *)((const unsigned char *)depth[0].contents + 5 * 256 + 5 * sizeof(float)) < 0.5f);
                }
                tests++;
            }
        }
        }
    }
    printf("%d Metal depth/stencil A/B comparisons passed (%s)\n", tests, device.name.UTF8String);
    return 0;
} }
