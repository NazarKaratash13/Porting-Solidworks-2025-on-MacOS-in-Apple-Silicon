#import "StoredPreview.h"

static NSError *missingImage(void)
{
    return [NSError errorWithDomain:@"local.solidworks2025.quicklook" code:1
                            userInfo:@{NSLocalizedDescriptionKey: @"В файле нет сохранённого изображения SOLIDWORKS."}];
}

#if SW_THUMBNAIL
#import <QuickLookThumbnailing/QuickLookThumbnailing.h>

@interface SWThumbnailProvider : QLThumbnailProvider
@end

@implementation SWThumbnailProvider
- (void)provideThumbnailForFileRequest:(QLFileThumbnailRequest *)request
                      completionHandler:(void (^)(QLThumbnailReply *, NSError *))completion
{
    id image = CFBridgingRelease(SWCopyStoredPreview(request.fileURL));
    if (!image)
    {
        completion(nil, missingImage());
        return;
    }

    CGImageRef pixels = (__bridge CGImageRef)image;
    CGFloat width = CGImageGetWidth(pixels), height = CGImageGetHeight(pixels);
    CGFloat scale = MIN(request.maximumSize.width / width, request.maximumSize.height / height);
    CGSize size = CGSizeMake(MAX(1, floor(width * scale)), MAX(1, floor(height * scale)));
    completion([QLThumbnailReply replyWithContextSize:size drawingBlock:^BOOL(CGContextRef context) {
        CGContextDrawImage(context, CGRectMake(0, 0, size.width, size.height), (__bridge CGImageRef)image);
        return YES;
    }], nil);
}
@end

#else
#import <QuickLookUI/QuickLookUI.h>

@interface SWPreviewProvider : QLPreviewProvider <QLPreviewingController>
@end

@implementation SWPreviewProvider
- (void)providePreviewForFileRequest:(QLFilePreviewRequest *)request
                  completionHandler:(void (^)(QLPreviewReply *, NSError *))completion
{
    id image = CFBridgingRelease(SWCopyStoredPreview(request.fileURL));
    if (!image)
    {
        completion(nil, missingImage());
        return;
    }

    CGImageRef pixels = (__bridge CGImageRef)image;
    CGSize size = CGSizeMake(CGImageGetWidth(pixels), CGImageGetHeight(pixels));
    QLPreviewReply *reply = [[QLPreviewReply alloc] initWithContextSize:size isBitmap:YES
        drawingBlock:^BOOL(CGContextRef context, QLPreviewReply *unused, NSError **error) {
            CGContextDrawImage(context, CGRectMake(0, 0, size.width, size.height), (__bridge CGImageRef)image);
            return YES;
        }];
    reply.title = request.fileURL.lastPathComponent;
    completion(reply, nil);
}
@end
#endif

extern int NSExtensionMain(int argc, char *argv[]);

int main(int argc, char *argv[])
{
    return NSExtensionMain(argc, argv);
}
