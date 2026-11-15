import type { NextConfig } from "next";

// The UI is exported as static files and served by nginx; there is no Node server in production.
const config: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
};

export default config;
