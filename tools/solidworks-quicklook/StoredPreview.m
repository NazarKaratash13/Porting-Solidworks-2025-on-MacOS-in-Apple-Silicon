#import "StoredPreview.h"
#import <ImageIO/ImageIO.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <zlib.h>

/* Modern stream marker and framing documented by Cameron Tacklind's cad-preview.
 * https://github.com/cinderblock/cad-preview/blob/main/src/formats/solidworks-modern.ts
 */
static const uint8_t streamMarker[] = {0x27, 0x56, 0x67, 0x96, 0x56, 0x77};
static const uint8_t pngMarker[] = {0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n'};
static const uint8_t compoundMarker[] = {0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1};
static const NSUInteger maxPreviewBytes = 4 * 1024 * 1024;
static const NSUInteger maxScanBytes = 128 * 1024 * 1024;

static uint32_t bigEndian32(const uint8_t *bytes)
{
    uint32_t value;
    memcpy(&value, bytes, sizeof(value));
    return CFSwapInt32BigToHost(value);
}

static BOOL hasImageContent(CGImageRef image)
{
    enum { side = 64, channels = 4 };
    uint8_t pixels[side * side * channels] = {0};
    CGColorSpaceRef colors = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
    if (!colors) return NO;
    CGContextRef context = CGBitmapContextCreate(pixels, side, side, 8, side * channels, colors,
                                                 (CGBitmapInfo)kCGImageAlphaPremultipliedLast);
    CGColorSpaceRelease(colors);
    if (!context) return NO;
    CGContextDrawImage(context, CGRectMake(0, 0, side, side), image);
    CGContextRelease(context);
    for (NSUInteger i = channels; i < sizeof(pixels); i += channels)
        if (memcmp(pixels, pixels + i, channels)) return YES;
    return NO;
}

static CGImageRef copyPNG(const uint8_t *bytes, NSUInteger length)
{
    if (length < 33 || memcmp(bytes, pngMarker, sizeof(pngMarker)) ||
        bigEndian32(bytes + 8) != 13 || memcmp(bytes + 12, "IHDR", 4)) return NULL;

    uint32_t width = bigEndian32(bytes + 16), height = bigEndian32(bytes + 20);
    if (!width || !height || width > 4096 || height > 4096) return NULL;

    for (NSUInteger offset = sizeof(pngMarker); length - offset >= 12;)
    {
        uint32_t chunkSize = bigEndian32(bytes + offset);
        if (chunkSize > length - offset - 12) return NULL;
        BOOL end = chunkSize == 0 && !memcmp(bytes + offset + 4, "IEND", 4);
        offset += chunkSize + 12;
        if (!end) continue;

        CFDataRef data = CFDataCreate(NULL, bytes, offset);
        if (!data) return NULL;
        CGImageSourceRef source = CGImageSourceCreateWithData(data, NULL);
        CFRelease(data);
        if (!source) return NULL;
        CGImageRef image = NULL;
        if (CGImageSourceGetStatusAtIndex(source, 0) == kCGImageStatusComplete)
            image = CGImageSourceCreateImageAtIndex(source, 0,
                (__bridge CFDictionaryRef)@{(__bridge NSString *)kCGImageSourceShouldCacheImmediately: @YES});
        CFRelease(source);
        if (image && !hasImageContent(image))
        {
            CGImageRelease(image);
            image = NULL;
        }
        return image;
    }
    return NULL;
}

static CGImageRef copyDeflatedPNG(int fd, off_t offset)
{
    uint8_t signature[sizeof(pngMarker)];
    uint8_t input[16384], output[16384];
    ssize_t n = pread(fd, input, sizeof(input), offset);
    if (n <= 0) return NULL;
    z_stream stream = {0};
    if (inflateInit2(&stream, -MAX_WBITS) != Z_OK) return NULL;
    NSUInteger readBytes = (NSUInteger)n;
    stream.next_in = input;
    stream.avail_in = (uInt)n;
    stream.next_out = signature;
    stream.avail_out = sizeof(signature);
    CGImageRef image = NULL;
    if (inflate(&stream, Z_NO_FLUSH) == Z_OK && !stream.avail_out &&
        !memcmp(signature, pngMarker, sizeof(signature)))
    {
        NSMutableData *png = [NSMutableData dataWithBytes:signature length:sizeof(signature)];
        int status;
        do {
            if (!stream.avail_in)
            {
                if (readBytes == maxPreviewBytes) break;
                n = pread(fd, input, MIN(sizeof(input), maxPreviewBytes - readBytes), offset + readBytes);
                if (n <= 0) break;
                stream.next_in = input;
                stream.avail_in = (uInt)n;
                readBytes += (NSUInteger)n;
            }
            stream.next_out = output;
            stream.avail_out = sizeof(output);
            status = inflate(&stream, Z_NO_FLUSH);
            NSUInteger count = sizeof(output) - stream.avail_out;
            if (count > maxPreviewBytes - png.length) break;
            [png appendBytes:output length:count];
            if (status == Z_STREAM_END) image = copyPNG(png.bytes, png.length);
        } while (status == Z_OK);
    }
    inflateEnd(&stream);
    return image;
}

static CGImageRef copyFileImage(int fd, off_t offset, off_t fileSize)
{
    NSMutableData *data = [NSMutableData dataWithLength:MIN((off_t)maxPreviewBytes, fileSize - offset)];
    ssize_t count = pread(fd, data.mutableBytes, data.length, offset);
    return count > 0 ? copyPNG(data.bytes, (NSUInteger)count) : NULL;
}

static CGImageRef scanFile(int fd, off_t size, BOOL compound, off_t start, off_t end)
{
    enum { chunkSize = 1024 * 1024 };
    const uint8_t *marker = compound ? pngMarker : streamMarker;
    NSUInteger markerLength = compound ? sizeof(pngMarker) : sizeof(streamMarker);
    NSMutableData *chunk = [NSMutableData dataWithLength:MIN((off_t)chunkSize, end - start)];
    NSUInteger records = 0;
    for (off_t offset = start; offset < end;)
    {
        ssize_t count = pread(fd, chunk.mutableBytes, MIN((off_t)chunk.length, end - offset), offset);
        if (count < (ssize_t)markerLength) break;
        const uint8_t *cursor = chunk.bytes, *limit = cursor + count;
        while (limit - cursor >= (ptrdiff_t)markerLength)
        {
            const uint8_t *match = memmem(cursor, limit - cursor, marker, markerLength);
            if (!match) break;
            if (++records > 4096) return NULL;
            off_t fileOffset = offset + (match - (const uint8_t *)chunk.bytes);
            @autoreleasepool
            {
                if (compound)
                {
                    CGImageRef image = copyFileImage(fd, fileOffset, size);
                    if (image) return image;
                }
                else
                {
                    /* +3 is the common frame observed in Parts, Assemblies and Drawings. */
                    static const unsigned offsets[] = {3, 0, 1, 2, 4, 5, 6, 7};
                    for (NSUInteger i = 0; i < sizeof(offsets) / sizeof(offsets[0]); ++i)
                    {
                        CGImageRef image = copyDeflatedPNG(fd, fileOffset + markerLength + offsets[i]);
                        if (image) return image;
                    }
                }
            }
            cursor = match + markerLength;
        }
        if (offset + count == end) break;
        offset += count - (markerLength - 1);
    }
    return NULL;
}

CGImageRef SWCopyStoredPreview(NSURL *url)
{
    NSString *suffix = url.pathExtension.lowercaseString;
    if (!url.isFileURL || ![@[@"sldprt", @"sldasm", @"slddrw"] containsObject:suffix]) return NULL;
    int fd = open(url.fileSystemRepresentation, O_RDONLY | O_CLOEXEC | O_NONBLOCK);
    if (fd < 0) return NULL;
    struct stat file;
    uint8_t signature[sizeof(compoundMarker)];
    CGImageRef image = NULL;
    if (!fstat(fd, &file) && S_ISREG(file.st_mode) && pread(fd, signature, sizeof(signature), 0) == sizeof(signature))
    {
        BOOL compound = !memcmp(signature, compoundMarker, sizeof(signature));
        image = scanFile(fd, file.st_size, compound, 0, MIN(file.st_size, (off_t)maxScanBytes));
        /* Large models can keep their preview alongside trailing metadata. */
        if (!image && file.st_size > (off_t)maxScanBytes)
        {
            off_t tail = MAX((off_t)maxScanBytes - (off_t)sizeof(pngMarker),
                             file.st_size - (off_t)maxScanBytes / 4);
            image = scanFile(fd, file.st_size, compound, tail, file.st_size);
        }
    }
    close(fd);
    return image;
}
