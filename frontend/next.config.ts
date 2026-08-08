import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: { unoptimized: true },
  /**
   * The "N" badge sitting over the sidebar footer in development is the
   * Next.js dev-tools indicator, not part of the application: nothing in
   * `src` renders a Next logo. It defaults to the bottom-left corner, which
   * is exactly where the sidebar footer is, so it reads as though Veyra were
   * showing the framework's own logo beside Profile and Log out.
   *
   * It never shipped to production - the `next build` output has no such
   * badge - but it made the footer look wrong every time the app was shown
   * locally, so it is switched off rather than explained away.
   *
   * Note: this file is parsed by SWC before the TypeScript pipeline and is
   * sensitive to non-ASCII bytes here, so the comment stays plain ASCII.
   */
  devIndicators: false,
};

export default nextConfig;
