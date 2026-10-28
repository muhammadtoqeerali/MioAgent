import type { NextConfig } from "next";
const nextConfig: NextConfig = { reactStrictMode: true, ...(process.env.MIO_S12C_BUILD_DIR === "build" ? { distDir: "build" } : {}) };
export default nextConfig;
