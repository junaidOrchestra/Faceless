/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone output produces a minimal server bundle for the Docker image.
  output: "standalone",
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "**" },
      { protocol: "http", hostname: "**" },
    ],
  },
};

export default nextConfig;
