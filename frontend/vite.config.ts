import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // 19000: el puerto que publica el compose de desarrollo. Ver el comentario
      // en deploy/docker-compose.dev.yml — Windows reserva el 8000.
      "/api": "http://localhost:19000",
    },
  },
});
