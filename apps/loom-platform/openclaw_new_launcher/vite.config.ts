import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  publicDir: process.env.LOOM_BRAND_VITE_PUBLIC_DIR?.trim() || 'public',
  server: {
    port: 1420,
    strictPort: true,
  },
  envPrefix: ['VITE_'],
});
