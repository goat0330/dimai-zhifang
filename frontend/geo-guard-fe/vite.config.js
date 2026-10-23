import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import postCssPxToRem from 'postcss-pxtorem'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    css: {
      postcss: {
        plugins: [
          postCssPxToRem({
            rootValue: 16,
            propList: ['*'],
            unitPrecision: 4,
            selectorBlackList: ['.norem', 'html'],
          }),
        ],
      },
    },
    server: {
      host: '0.0.0.0',
      port: 5174,
      proxy: {
        '/yichang-gold': {
          target: env.VITE_YICHANG_GOLD_API_URL || 'http://127.0.0.1:8011',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/yichang-gold/, ''),
        },
      },
    },
  }
})
