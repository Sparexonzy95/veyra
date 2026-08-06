import { cn } from "@/lib/utils";

/**
 * The approved Veyra "V" mark, rendered using the same luminance-to-alpha
 * knockout technique as the wordmark. The source JPG is 1280×1148 with dark
 * glyphs (luminance ~0.00) on a sand plate (luminance >0.55). The glyph
 * bounding box is x 376-974, y 290-860, so the viewBox crops to that region.
 */
export function VeyraMark({
  uid,
  color = "#050505",
  className,
  title = "Veyra",
}: {
  uid: string;
  color?: string;
  className?: string;
  title?: string;
}) {
  const filterId = `veyra-mark-knockout-${uid}`;

  return (
    <svg
      viewBox="376 290 598 570"
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
          colorInterpolationFilters="sRGB"
        >
          <feColorMatrix
            type="matrix"
            values="0 0 0 0 0
                    0 0 0 0 0
                    0 0 0 0 0
                    -0.2126 -0.7152 -0.0722 0 1"
            result="inverted"
          />
          <feComponentTransfer in="inverted" result="cutout">
            <feFuncA type="linear" slope="2.5" intercept="-1.15" />
          </feComponentTransfer>
          <feFlood floodColor={color} result="ink" />
          <feComposite in="ink" in2="cutout" operator="in" />
        </filter>
      </defs>

      <image
        href="/brand/veyra-mark.jpg"
        x="0"
        y="0"
        width="1280"
        height="1148"
        filter={`url(#${filterId})`}
        preserveAspectRatio="none"
      />
    </svg>
  );
}
