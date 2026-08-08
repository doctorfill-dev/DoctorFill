import { execSync } from "child_process"
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

// Cloudflare Pages construit sur un clone superficiel où `git describe` n'a pas
// de tag à quoi se raccrocher : sa variable d'environnement fait autorité, et le
// dépôt local ne sert que de repli pour les builds sur poste.
function readCommit(): string {
  const fromCI = process.env.CF_PAGES_COMMIT_SHA || process.env.GITHUB_SHA
  if (fromCI) return fromCI.slice(0, 7)
  try {
    return execSync("git describe --always --dirty --abbrev=7", {
      cwd: __dirname,
      stdio: ["ignore", "pipe", "ignore"],
    }).toString().trim()
  } catch {
    return "inconnu"
  }
}

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(readVersion()),
    __APP_COMMIT__: JSON.stringify(readCommit()),
    __APP_BUILT_AT__: JSON.stringify(new Date().toISOString().slice(0, 16) + "Z"),
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
})
