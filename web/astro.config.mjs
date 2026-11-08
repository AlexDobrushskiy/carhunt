import { defineConfig } from 'astro/config';
import node from '@astrojs/node';
import react from '@astrojs/react';
import tailwind from '@tailwindcss/vite';

export default defineConfig({
  output: 'server',
  adapter: node({ mode: 'standalone' }),
  integrations: [react()],
  vite: { plugins: [tailwind()] },
  server: { host: '127.0.0.1', port: 4321 },
  // Writes are checked in the /ui proxy (sameOrigin), which also honours X-Forwarded-Host behind a reverse proxy.
  security: { checkOrigin: false },
  compressHTML: true,
  devToolbar: { enabled: false },
});
