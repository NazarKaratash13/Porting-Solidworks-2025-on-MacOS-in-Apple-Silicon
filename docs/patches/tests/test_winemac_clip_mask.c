#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <CoreGraphics/CoreGraphics.h>

typedef struct { int32_t left, top, right, bottom; } RECT;
#include "gl_clip_region.h"

static CGRect scale_rect(RECT rect, double factor)
{
    return CGRectMake(rect.left * factor, rect.top * factor,
                      (rect.right - rect.left) * factor, (rect.bottom - rect.top) * factor);
}

int main(void)
{
    const RECT client = {0, 0, 16, 16};
    const RECT cuts[] = {{2, 2, 12, 6}, {2, 2, 6, 12}};
    const double scales[] = {1.0, 0.5};
    struct gl_clip_region holes = {0};

    assert(gl_clip_union_in_client(&holes, client, cuts, 2));
    for (size_t scale = 0; scale < 2; ++scale)
    {
        const double factor = scales[scale];
        CGMutablePathRef legacy = CGPathCreateMutable();
        CGMutablePathRef candidate = CGPathCreateMutable();
        unsigned int legacy_mismatches = 0;

        CGPathAddRect(legacy, NULL, scale_rect(client, factor));
        CGPathAddRect(legacy, NULL, CGRectUnion(scale_rect(cuts[0], factor),
                                                scale_rect(cuts[1], factor)));
        CGPathAddRect(candidate, NULL, scale_rect(client, factor));
        for (size_t i = 0; i < holes.count; ++i)
            CGPathAddRect(candidate, NULL, scale_rect(holes.rects[i], factor));

        for (int y = 0; y < client.bottom; ++y)
            for (int x = 0; x < client.right; ++x)
            {
                CGPoint point = CGPointMake((x + .5) * factor, (y + .5) * factor);
                bool visible = !CGRectContainsPoint(scale_rect(cuts[0], factor), point) &&
                               !CGRectContainsPoint(scale_rect(cuts[1], factor), point);
                if (visible != CGPathContainsPoint(legacy, NULL, point, true))
                    ++legacy_mismatches;
                assert(visible == CGPathContainsPoint(candidate, NULL, point, true));
            }
        assert(legacy_mismatches == 36);
        printf("Scale %.1f pt/px: legacy 36/256 wrong, candidate 0/256 wrong\n", factor);
        CGPathRelease(legacy);
        CGPathRelease(candidate);
    }
    gl_clip_clear(&holes);
    return 0;
}
