import path from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const directory = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  base: "/static/excalidraw/",
  plugins: [react()],
  build: {
    outDir: path.resolve(directory, "../src/voice_interviewer/static/excalidraw"),
    emptyOutDir: true,
    cssCodeSplit: false,
    rollupOptions: {
      input: path.resolve(directory, "src/main.jsx"),
      output: {
        entryFileNames: "diagram-app.js",
        chunkFileNames: "chunks/[name]-[hash].js",
        assetFileNames: (assetInfo) => {
          const names = [...(assetInfo.names ?? []), assetInfo.name ?? ""];
          return names.some((name) => name.endsWith(".css"))
            ? "diagram-app.css"
            : "assets/[name]-[hash][extname]";
        },
      },
    },
  },
});
