import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolveAssetsRoot, assetMiddleware } from './scripts/assets.mjs'

// Serves /manifest.json and /assets/* from the asset root during `npm run dev` / `npm run preview`.
// The production build is plain static files; serve.py provides the same two routes.
function tod() {
  const root = resolveAssetsRoot()
  return {
    name: 'tod-assets',
    configureServer(server) {
      server.config.logger.info(`  TOD assets: ${root}`)
      server.middlewares.use(assetMiddleware(root))
    },
    configurePreviewServer(server) { server.middlewares.use(assetMiddleware(root)) },
  }
}

export default defineConfig({
  base: './',
  plugins: [react(), tod()],
  // The viewer's own JS/CSS go to dist/_app so dist/assets stays free for the extracted models.
  build: { assetsDir: '_app', chunkSizeWarningLimit: 2000 },
  server: { port: 5190, strictPort: false },
  preview: { port: 5191 },
})
