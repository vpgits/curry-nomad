/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Pin the workspace root to this app so Next doesn't infer a stray parent lockfile.
  turbopack: {
    root: import.meta.dirname,
  },
  // The signed-in operator's Google profile photo (next/image in the sidebar account row).
  images: {
    remotePatterns: [{ protocol: "https", hostname: "*.googleusercontent.com" }],
  },
};

export default nextConfig;
