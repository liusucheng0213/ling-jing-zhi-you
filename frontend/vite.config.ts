import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// Vite配置 - 灵境智游前端
export default defineConfig({
  plugins: [
    react(),
    // PWA插件配置，支持添加到主屏幕
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: '灵境智游',
        short_name: '灵境智游',
        description: 'AI数字人导览系统',
        theme_color: '#2D5A87',
        background_color: '#FFF8E7',
        display: 'standalone',
        icons: [
          {
            src: '/icon-192x192.png',
            sizes: '192x192',
            type: 'image/png'
          },
          {
            src: '/icon-512x512.png',
            sizes: '512x512',
            type: 'image/png'
          }
        ]
      }
    })
  ],
  server: {
    port: 3000,
    host: true,
    proxy: {
      '/api': {
        target: process.env.VITE_DEV_API_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('react-dom') || id.includes('react-router') || /[\\/]react[\\/]/.test(id)) return 'react-vendor'
          if (id.includes('antd-mobile')) return 'antd-mobile-vendor'
          if (id.includes('@ant-design/icons') || /[\\/]antd[\\/]/.test(id)) return 'antd-vendor'
          if (id.includes('framer-motion')) return 'motion-vendor'
          if (id.includes('zustand')) return 'state-vendor'
          return undefined
        },
      },
    },
  }
})
