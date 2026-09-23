const config = {
  output: 'standalone',
  // Compression can buffer long-lived event streams behind the same-origin proxy.
  compress: false,
  async headers() {
    return [{source: '/sw.js', headers: [
      {key: 'Cache-Control', value: 'no-store'},
      {key: 'Service-Worker-Allowed', value: '/'},
      {key: 'X-Content-Type-Options', value: 'nosniff'},
    ]}];
  },
  async rewrites() {
    return [{source: '/v1/:path*', destination: `${process.env.API_INTERNAL_URL || 'http://127.0.0.1:8000'}/v1/:path*`}];
  },
};
export default config;
