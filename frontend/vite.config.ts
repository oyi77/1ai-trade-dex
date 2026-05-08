import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { visualizer } from 'rollup-plugin-visualizer'
import viteCompression from 'vite-plugin-compression'

export default defineConfig({
  resolve: {
    dedupe: ['d3-selection'],
  },
  plugins: [
    react(),
    visualizer({
      filename: './dist/stats.html',
      open: false,
      gzipSize: true,
      brotliSize: true,
    }),
    viteCompression({
      algorithm: 'gzip',
      ext: '.gz',
    }),
    viteCompression({
      algorithm: 'brotliCompress',
      ext: '.br',
    }),
  ],
  build: {
    chunkSizeWarningLimit: 500,
    minify: 'esbuild',
    rollupOptions: {
      output: {
        manualChunks: (id) => {
          if (id.includes('node_modules')) {
            if (id.includes('react') || id.includes('react-dom') || id.includes('react-router-dom') || id.includes('@tanstack/react-query') || id.includes('reactflow') || id.includes('d3-zoom') || id.includes('d3-selection') || id.includes('d3-transition') || id.includes('d3-drag')) {
              return 'vendor-react'
            }
            if (id.includes('framer-motion') || id.includes('lucide-react')) {
              return 'vendor-ui'
            }
            if (id.includes('mapbox-gl') || id.includes('react-map-gl') || id.includes('react-simple-maps') || id.includes('leaflet') || id.includes('react-leaflet') || id.includes('d3-geo')) {
              return 'vendor-maps'
            }
            if (id.includes('three') || id.includes('react-globe.gl') || id.includes('globe.gl')) {
              return 'vendor-three'
            }
          }
        },
      },
    },
  },
  server: {
    port: 5174,
    host: process.env.VITE_DEV_EXTERNAL === '1' ? '0.0.0.0' : 'localhost',
    allowedHosts: ['polyedge.aitradepulse.com', 'localhost', '127.0.0.1'],
    proxy: {
      '/api': {
        target: process.env.VITE_BACKEND_URL || 'http://127.0.0.1:8100',
        changeOrigin: true
      },
      '/ws': {
        target: (process.env.VITE_BACKEND_URL || 'http://127.0.0.1:8100').replace(/^http/, 'ws'),
        ws: true,
        changeOrigin: true
      }
    }
  },
  preview: {
    host: process.env.VITE_DEV_EXTERNAL === '1' ? '0.0.0.0' : 'localhost',
    port: 5174,
    allowedHosts: ['polyedge.aitradepulse.com', 'localhost'],
    proxy: {
      '/api': {
        target: process.env.VITE_BACKEND_URL || 'http://127.0.0.1:8100',
        changeOrigin: true
      },
      '/ws': {
        target: (process.env.VITE_BACKEND_URL || 'http://127.0.0.1:8100').replace(/^http/, 'ws'),
        ws: true,
        changeOrigin: true
      }
    }
  }
})
