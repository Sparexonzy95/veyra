import { cn } from "@/lib/utils";

/**
 * The approved wordmark artwork is a JPG: black glyphs baked onto an opaque
 * sand plate. Rendered directly it always reads as a logo trapped in a badge.
 *
 * Rather than editing the approved file, this renders it through an SVG filter:
 *   1. luminance is converted to alpha (dark glyphs -> opaque, plate -> clear)
 *   2. a linear transfer sharpens that into a clean cutout
 *   3. the result is flooded with the requested brand colour
 *
 * Measurements taken from the file justify the thresholds: glyph luminance is
 * ~0.00, the plate never drops below 0.55, and only 0.12% of pixels fall
 * between, so the knockout is clean rather than approximate.
 *
 * The viewBox crops to the measured glyph bounding box (x 343-910, y 235-411
 * of 1280x652) so the surrounding plate padding does not shrink the mark.
 */
export function VeyraWordmark({
  uid,
  color = "#050505",
  className,
  title = "Veyra",
}: {
  /** Unique per instance: SVG filter ids must not collide in one document. */
  uid: string;
  color?: string;
  className?: string;
  title?: string;
}) {
  const filterId = `veyra-wordmark-knockout-${uid}`;

  return (
    <svg
      viewBox="343 235 568 177"
      role="img"
      aria-label={title}
      className={cn("block h-auto w-full", className)}
    >
      <defs>
        <filter
          id={filterId}
          x="0%"
          y="0%"
          width="100%"
          height="100%"
          // sRGB keeps the luminance maths aligned with the measured pixel
          // values; the default linearRGB would shift the threshold.
          colorInterpolationFilters="sRGB"
        >
          {/* alpha = 1 - luminance */}
          <feColorMatrix
            type="matrix"
            values="0 0 0 0 0
                    0 0 0 0 0
                    0 0 0 0 0
                    -0.2126 -0.7152 -0.0722 0 1"
            result="inverted"
          />
          {/* Sharpen the transition so no sand haze remains. */}
          <feComponentTransfer in="inverted" result="cutout">
            <feFuncA type="linear" slope="2.5" intercept="-1.15" />
          </feComponentTransfer>
          <feFlood floodColor={color} result="ink" />
          {/* Clip the flood to the cutout, not to the opaque source image. */}
          <feComposite in="ink" in2="cutout" operator="in" />
        </filter>

      </defs>

      <image
        href="/brand/veyra-wordmark.jpg"
        x="0"
        y="0"
        width="1280"
        height="652"
        filter={`url(#${filterId})`}
        preserveAspectRatio="none"
      />
    </svg>
  );
}
