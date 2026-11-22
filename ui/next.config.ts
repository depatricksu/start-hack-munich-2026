import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The Next.js dev badge sits bottom-left, right on top of the account avatar. Off: it is not part of the UI.
  devIndicators: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
