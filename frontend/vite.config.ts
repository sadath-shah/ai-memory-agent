import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Builds the web app (sidebar, chat, memory management) into ../static (served by the Python backend).
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    outDir: "../static",
    emptyOutDir: false, // static/ also holds index.html
    lib: {
      entry: "src/main.tsx",
      name: "__MemoryAgentApp",
      formats: ["iife"],
      fileName: () => "app.js",
      cssFileName: "app",
    },
  },
});
