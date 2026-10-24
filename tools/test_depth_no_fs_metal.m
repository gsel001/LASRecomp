// Standalone synthetic Metal regression: no window, game library, shaders, assets or saves.
#import <Metal/Metal.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(void) { @autoreleasepool {
    id<MTLDevice> device = MTLCreateSystemDefaultDevice();
    if (!device) { fprintf(stderr, "SKIP: no Metal device\n"); return 77; }
    NSError *error = nil;
    NSString *source = @"#include <metal_stdlib>\nusing namespace metal;\n"
        "vertex float4 vs(uint i [[vertex_id]], constant float &z [[buffer(0)]]) {"
        " float2 p[3] = {float2(-1,-1),float2(3,-1),float2(-1,3)}; return float4(p[i],z,1); }\n"
        "fragment float4 fs() { return float4(0.2,0.4,0.6,1); }\n";
    id<MTLLibrary> library = [device newLibraryWithSource:source options:nil error:&error];
    if (!library) { fprintf(stderr, "%s\n", error.localizedDescription.UTF8String); return 1; }
    id<MTLCommandQueue> queue = [device newCommandQueue];
    int tests = 0;
    for (int combined = 0; combined < 2; combined++) {
        MTLPixelFormat format = combined ? MTLPixelFormatDepth32Float_Stencil8 : MTLPixelFormatDepth32Float;
        for (int comparison = MTLCompareFunctionNever; comparison <= MTLCompareFunctionAlways; comparison++) {
            for (int bias = 0; bias < 2; bias++) {
                id<MTLBuffer> depth[2], stencil[2];
                for (int omit = 0; omit < 2; omit++) {
                    MTLRenderPipelineDescriptor *pipeline = [MTLRenderPipelineDescriptor new];
                    pipeline.vertexFunction = [library newFunctionWithName:@"vs"];
                    pipeline.fragmentFunction = omit ? nil : [library newFunctionWithName:@"fs"];
                    pipeline.depthAttachmentPixelFormat = format;
                    if (combined) pipeline.stencilAttachmentPixelFormat = format;
                    id<MTLRenderPipelineState> state = [device newRenderPipelineStateWithDescriptor:pipeline error:&error];
                    if (!state) { fprintf(stderr, "%s\n", error.localizedDescription.UTF8String); return 1; }
                    MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:format
                                                          width:16 height:16 mipmapped:NO];
                    td.usage = MTLTextureUsageRenderTarget;
                    td.storageMode = MTLStorageModePrivate;
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
                    MTLDepthStencilDescriptor *ds = [MTLDepthStencilDescriptor new];
                    ds.depthCompareFunction = comparison;
                    ds.depthWriteEnabled = YES; // stencil stays disabled, as required by the experiment
                    id<MTLCommandBuffer> command = [queue commandBuffer];
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
                    depth[omit] = [device newBufferWithLength:4096 options:MTLResourceStorageModeShared];
                    stencil[omit] = [device newBufferWithLength:4096 options:MTLResourceStorageModeShared];
                    id<MTLBlitCommandEncoder> blit = [command blitCommandEncoder];
                    [blit copyFromTexture:target sourceSlice:0 sourceLevel:0 sourceOrigin:(MTLOrigin){0,0,0}
                               sourceSize:(MTLSize){16,16,1} toBuffer:depth[omit] destinationOffset:0
                     destinationBytesPerRow:256 destinationBytesPerImage:4096
                                   options:combined ? MTLBlitOptionDepthFromDepthStencil : MTLBlitOptionNone];
                    if (combined)
                        [blit copyFromTexture:target sourceSlice:0 sourceLevel:0 sourceOrigin:(MTLOrigin){0,0,0}
                                   sourceSize:(MTLSize){16,16,1} toBuffer:stencil[omit] destinationOffset:0
                         destinationBytesPerRow:256 destinationBytesPerImage:4096 options:MTLBlitOptionStencilFromDepthStencil];
                    [blit endEncoding];
                    [command commit];
                    [command waitUntilCompleted];
                    if (command.status != MTLCommandBufferStatusCompleted) {
                        fprintf(stderr, "%s\n", command.error.localizedDescription.UTF8String); return 1;
                    }
                }
                for (int y = 0; y < 16; y++) {
                    const unsigned char *a = depth[0].contents, *b = depth[1].contents;
                    assert(!memcmp(a + y * 256, b + y * 256, 16 * sizeof(float)));
                    if (combined) {
                        a = stencil[0].contents; b = stencil[1].contents;
                        assert(!memcmp(a + y * 256, b + y * 256, 16));
                        for (int x = 0; x < 16; x++) assert(b[y * 256 + x] == 7);
                    }
                }
                // Verify the readback actually contains the clear value outside the scissor.
                assert(*(const float *)depth[0].contents == 0.5f);
                if (comparison == MTLCompareFunctionLess && !bias)
                    assert(*(const float *)((const unsigned char *)depth[0].contents + 5 * 256 + 5 * sizeof(float)) == 0.25f);
                tests++;
            }
        }
    }
    printf("%d Metal depth/stencil A/B comparisons passed (%s)\n", tests, device.name.UTF8String);
    return 0;
} }
