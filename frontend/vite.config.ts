import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';
export default defineConfig({ plugins: [react()], build: { rollupOptions: { input: { main: fileURLToPath(new URL('./index.html', import.meta.url)), driver: fileURLToPath(new URL('./driver.html', import.meta.url)) } } }, server: { port: 5173, strictPort: true, proxy: { '/api': { target: process.env.ZELVO_API_URL || 'http://127.0.0.1:8000', ws: true } } } });
