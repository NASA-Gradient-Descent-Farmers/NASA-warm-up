import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  base: './', // relative asset paths: the built app works from any folder or static host
  plugins: [react()],
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
})
