/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone output produces a minimal server bundle for the Docker image.
  output: "standalone",
  // Production uploads go browser->bucket directly (presigned multipart), but
  // the local/dev fallback still proxies the file through /api/videos. Raise the
  // proxy/middleware body buffer so that path isn't capped at the 10MB default.
  experimental: {
    proxyClientMaxBodySize: "3gb",
  },
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "**" },
      { protocol: "http", hostname: "**" },
    ],
  },
};

export default nextConfig;
