import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "node:path";

export default defineConfig({
  root: path.resolve(__dirname),
  base: "/map-studio/",
  plugins: [react()],
  resolve: { alias: { "@map-studio": path.resolve(__dirname, "src") } },
  server: { host: "127.0.0.1", port: 4182 },
  build: { outDir: path.resolve(__dirname, "dist"), emptyOutDir: true },
});
