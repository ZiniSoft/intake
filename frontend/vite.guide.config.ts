import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'

// styles.css loads fonts from /fonts/, the site root of the app. On GitHub Pages the guide lives under /<repo>/, so
// the built stylesheet (in assets/) points one level up instead.
const relativeFonts: Plugin = {
  name: 'guide-relative-fonts',
  apply: 'build',
  generateBundle(_options, bundle) {
    for (const name in bundle) {
      const file = bundle[name]
      if (file.type === 'asset' && file.fileName.endsWith('.css') && typeof file.source === 'string') {
        file.source = file.source.replace(/url\((['"]?)\/fonts\//g, 'url($1../fonts/')
      }
    }
  },
}

// Static build of the public guide for GitHub Pages (FR-UI-18). Relative paths, so it works under /<repo>/.
export default defineConfig({
  plugins: [react(), relativeFonts],
  base: './',
  build: {
    outDir: 'dist-guide',
    emptyOutDir: true,
    rollupOptions: { input: 'guide.html' },
  },
})
