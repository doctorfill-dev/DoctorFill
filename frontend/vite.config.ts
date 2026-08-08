import fs from "fs"
import path from "path"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

// Source unique de vérité : le fichier VERSION à la racine du dépôt, partagé avec
// le backend. Le frontend et l'orchestrateur étant déployés séparément (Cloudflare
// Pages d'un côté, DGX Spark de l'autre), l'application affiche les deux versions
// — c'est leur divergence qui est le signal utile.
function readVersion(): string {
  try {
    return fs.readFileSync(path.resolve(__dirname, "../VERSION"), "utf-8").trim()
  } catch {
    return "inconnue"
  }
}

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(readVersion()),
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
})
