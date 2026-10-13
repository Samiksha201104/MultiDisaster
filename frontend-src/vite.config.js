import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The FastAPI backend (app.py) does two things we must not touch:
//   1. app.mount("/static", StaticFiles(directory=STATIC))
//   2. GET "/" -> FileResponse(STATIC / "index.html")
// So this build must emit an index.html + hashed asset files into that same
// "static" directory, with asset URLs rooted at /static/.
export default defineConfig({
  plugins: [react()],
  base: '/static/',
  build: {
    outDir: '../static',
    emptyOutDir: true,
  },
});
