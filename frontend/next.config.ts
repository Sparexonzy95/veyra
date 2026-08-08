import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: { unoptimized: true },

  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "https://api.veyra.surf/api/:path*",
      },
    ];
  },

  devIndicators: false,
};

export default nextConfig;