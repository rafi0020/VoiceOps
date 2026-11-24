import type { NextConfig } from "next";

// The UI is exported as static files and served by nginx; there is no Node server in production.
const config: NextConfig = {
  output: "export",
  // Set only for the GitHub Pages demo, which is served under /<repository>/.
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || undefined,
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
};

export default config;
