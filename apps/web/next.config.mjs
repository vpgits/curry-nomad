/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Pin the workspace root to this app so Next doesn't infer a stray parent lockfile.
  turbopack: {
    root: import.meta.dirname,
  },
};

export default nextConfig;
