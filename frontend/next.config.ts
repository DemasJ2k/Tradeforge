import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",  // self-contained build for non-Vercel hosts (Render, Docker, etc.)
};

export default nextConfig;
