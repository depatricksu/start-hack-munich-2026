import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The Next.js dev badge sits bottom-left, right on top of the account avatar. Off: it is not part of the UI.
  devIndicators: false,
  // Relay v2 (Kai, ui/app/v2) is the product interface: Erik, 22 Nov 12:03, "replace current UI with his UI".
  // The screens of the first version that v2 has too now open v2. The ones v2 does not have yet
  // (/carriers, /workflow, /dashboard, /score) stay where they are. Undo: remove this block.
  async redirects() {
    return [
      { source: "/", destination: "/v2", permanent: false },
      { source: "/requests", destination: "/v2/requests", permanent: false },
      { source: "/shipments", destination: "/v2/shipments", permanent: false },
      { source: "/invoices", destination: "/v2/invoices", permanent: false },
    ];
  },
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
