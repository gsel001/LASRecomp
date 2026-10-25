// Tiny asset-free capability probe; no game code, shaders, saves or benchmark loops.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <CoreGraphics/CoreGraphics.h>
#include <unistd.h>
int main(int argc,const char **argv){@autoreleasepool{
 id<MTLDevice>d=MTLCreateSystemDefaultDevice();if(!d){fprintf(stderr,"No Metal device\n");return 1;}
 CGDisplayModeRef mode=CGDisplayCopyDisplayMode(CGMainDisplayID());
 NSDictionary*m=@{@"gpu":d.name,@"thermal_state":@([NSProcessInfo processInfo].thermalState),@"display_points":@[@(CGDisplayModeGetWidth(mode)),@(CGDisplayModeGetHeight(mode))],@"display_pixels":@[@(CGDisplayModeGetPixelWidth(mode)),@(CGDisplayModeGetPixelHeight(mode))]};
 puts([[NSString alloc]initWithData:[NSJSONSerialization dataWithJSONObject:m options:0 error:nil] encoding:NSUTF8StringEncoding].UTF8String);fflush(stdout);CGDisplayModeRelease(mode);
 if(argc<2)return 0;
 id<MTLCommandQueue>q=[d newCommandQueue];q.label=@"Synthetic capability probe";
 id<MTLCaptureScope>scope=[[MTLCaptureManager sharedCaptureManager]newCaptureScopeWithCommandQueue:q];scope.label=@"Synthetic scope";[MTLCaptureManager sharedCaptureManager].defaultCaptureScope=scope;
 MTLTextureDescriptor*td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:64 height:64 mipmapped:NO];td.usage=MTLTextureUsageRenderTarget;td.storageMode=MTLStorageModePrivate;
 id<MTLTexture>t=[d newTextureWithDescriptor:td];
 for(int n=0;n<atoi(argv[1])*20;n++){@autoreleasepool{[scope beginScope];id<MTLCommandBuffer>c=[q commandBuffer];c.label=@"Synthetic clear";MTLRenderPassDescriptor*p=[MTLRenderPassDescriptor new];p.colorAttachments[0].texture=t;p.colorAttachments[0].loadAction=MTLLoadActionClear;p.colorAttachments[0].storeAction=MTLStoreActionDontCare;[[c renderCommandEncoderWithDescriptor:p]endEncoding];[c commit];[c waitUntilCompleted];[scope endScope];if(c.error){fprintf(stderr,"%s\n",c.error.description.UTF8String);return 1;}usleep(50000);}}
 return 0;
}}
