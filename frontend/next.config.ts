import type { NextConfig } from "next";

/**
 * Static export: `next build` writes plain HTML/JS to ./out, which the Dockerfile copies into
 * the FastAPI `static/` folder so the dashboard and the API ship as one Render service.
 * The UI lives under /app so it never collides with the REST API (GET /patients is JSON).
 * All data fetching happens client-side against the same origin (or NEXT_PUBLIC_API_URL in dev).
 */
const nextConfig: NextConfig = {
  output: "export",
  basePath: "/app",
  trailingSlash: false,
  images: { unoptimized: true },
  reactStrictMode: true,
};

export default nextConfig;
