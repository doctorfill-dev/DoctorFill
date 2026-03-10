import { useState } from "react";
import { Terminal, Database, FileOutput, Lock, ChevronRight, Mail, X } from "lucide-react";
import { Link } from "react-router-dom";

export default function Landing() {
  const [showContact, setShowContact] = useState(false);
  const [contactSent, setContactSent] = useState(false);
  const [contactLoading, setContactLoading] = useState(false);

  const handleContactSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setContactLoading(true);
    const form = e.currentTarget;
    const data = new FormData(form);
    try {
      const res = await fetch("https://formspree.io/f/mwpodjlq", {
        method: "POST",
        body: data,
        headers: { Accept: "application/json" },
      });
      if (res.ok) {
        setContactSent(true);
        form.reset();
      }
    } catch {
      // silently fail
    } finally {
      setContactLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#FDFDFD] text-zinc-900 font-sans selection:bg-emerald-100 selection:text-emerald-900">

      {/* NAVIGATION TECHNIQUE */}
      <nav className="max-w-5xl mx-auto px-6 py-6 flex items-center justify-between border-b border-zinc-200">
        <div className="font-semibold tracking-tight text-xl flex items-center gap-3">
          <img
            src="/logo.png"
            alt="DoctorFill"
            className="w-10 h-10 rounded-md shadow-sm border border-zinc-200"
          />
          doctorfill-dev.
        </div>

        <div className="flex items-center gap-4 text-sm font-medium">
          <Link
            to="/app"
            className="flex items-center gap-2 bg-zinc-900 text-white px-4 py-2 rounded-sm hover:bg-zinc-800 transition-colors"
          >
            <Lock className="w-3.5 h-3.5" />
            Accès Interface
          </Link>
        </div>
      </nav>

      <main className="max-w-5xl mx-auto px-6">

        {/* EN-TÊTE FACTUEL */}
        <section className="py-20 max-w-3xl">
          <div className="inline-flex items-center gap-2 px-2.5 py-1 bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-sm text-xs font-mono mb-6">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
            Statut : En développement actif (Suisse)
          </div>

          <h1 className="text-4xl md:text-5xl font-bold tracking-tight text-zinc-900 mb-6">
            Projet DoctorFill
          </h1>

          <p className="text-lg text-zinc-600 leading-relaxed mb-8">
            DoctorFill est un outil expérimental conçu pour extraire les informations pertinentes de dossiers médicaux non structurés (PDF, ZIP) et pré-remplir automatiquement des formulaires administratifs complexes (format XFA).
          </p>

          <div className="flex flex-col sm:flex-row gap-3">
            <Link
              to="/app"
              className="inline-flex items-center justify-center bg-zinc-100 border border-zinc-300 text-zinc-900 px-5 py-2.5 rounded-sm text-sm font-medium hover:bg-zinc-200 transition-colors"
            >
              Tester l'application <ChevronRight className="ml-1 w-4 h-4" />
            </Link>

            <button
              onClick={() => { setShowContact(true); setContactSent(false); }}
              className="inline-flex items-center justify-center bg-transparent border border-zinc-300 text-zinc-600 px-5 py-2.5 rounded-sm text-sm font-medium hover:border-zinc-400 hover:text-zinc-900 transition-colors"
            >
              <Mail className="mr-2 w-4 h-4" />
              Me contacter
            </button>
          </div>
        </section>

        {/* LIGNE DE SÉPARATION */}
        <hr className="border-zinc-200" />

        {/* EXPLICATION DU FONCTIONNEMENT (Architecture) */}
        <section className="py-16">
          <h2 className="text-xl font-semibold mb-8">Architecture et Fonctionnement</h2>

          <div className="grid md:grid-cols-3 gap-6">

            {/* Étape 1 */}
            <div className="p-6 border border-zinc-200 rounded-sm bg-zinc-50/50 relative">
              <div className="absolute top-0 right-0 p-4 opacity-10 font-mono text-4xl font-bold">01</div>
              <Terminal className="w-5 h-5 text-zinc-700 mb-4" />
              <h3 className="text-base font-semibold mb-2">Ingestion & OCR</h3>
              <p className="text-sm text-zinc-600 leading-relaxed">
                Les documents fournis sont analysés localement. Le texte est extrait via des modèles d'OCR avancés (Marker) pour convertir les images et PDF scannés en format Markdown structuré.
              </p>
            </div>

            {/* Étape 2 */}
            <div className="p-6 border border-zinc-200 rounded-sm bg-zinc-50/50 relative">
              <div className="absolute top-0 right-0 p-4 opacity-10 font-mono text-4xl font-bold">02</div>
              <Database className="w-5 h-5 text-zinc-700 mb-4" />
              <h3 className="text-base font-semibold mb-2">Vectorisation & LLM</h3>
              <p className="text-sm text-zinc-600 leading-relaxed">
                Le contexte est découpé et vectorisé. Un modèle de langage (Qwen 14B) interroge cette base de données vectorielle pour trouver les réponses spécifiques exigées par le formulaire.
              </p>
            </div>

            {/* Étape 3 */}
            <div className="p-6 border border-zinc-200 rounded-sm bg-zinc-50/50 relative">
              <div className="absolute top-0 right-0 p-4 opacity-10 font-mono text-4xl font-bold">03</div>
              <FileOutput className="w-5 h-5 text-zinc-700 mb-4" />
              <h3 className="text-base font-semibold mb-2">Injection XFA</h3>
              <p className="text-sm text-zinc-600 leading-relaxed">
                Les réponses extraites sont formatées et injectées dans l'arborescence XML d'un fichier PDF vierge, générant le document final sans altérer sa structure officielle.
              </p>
            </div>

          </div>
        </section>

        {/* CONTRAINTE TECHNIQUE / SÉCURITÉ */}
        <section className="py-12 mb-16 bg-zinc-900 text-zinc-300 rounded-sm p-8 border border-zinc-800">
          <div className="flex items-start gap-4">
            <Lock className="w-6 h-6 text-emerald-500 shrink-0 mt-1" />
            <div>
              <h3 className="text-lg font-semibold text-white mb-2">Infrastructure On-Premise</h3>
              <p className="text-sm leading-relaxed max-w-3xl">
                Par principe éthique et légal lié aux données médicales, l'ensemble de la pipeline (OCR, Embeddings, LLM) s'exécute sur un serveur dédié (NVIDIA DGX). L'application ne fait <strong>aucun appel à des API externes</strong> (ni OpenAI, ni Anthropic). Le réseau est isolé.
              </p>
            </div>
          </div>
        </section>

      </main>

      {/* FOOTER SIMPLE */}
      <footer className="border-t border-zinc-200 py-8">
        <div className="max-w-5xl mx-auto px-6 flex flex-col md:flex-row justify-between items-center gap-4 text-xs text-zinc-500">
          <div>
            doctorfill-dev © {new Date().getFullYear()} — Créé pour le domaine médical.
          </div>
          <div>
            Neuchâtel, CH.
          </div>
        </div>
      </footer>

      {/* MODAL CONTACT */}
      {showContact && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={() => setShowContact(false)}>
          <div className="bg-white border border-zinc-200 rounded-sm shadow-lg w-full max-w-md mx-4 p-6 relative" onClick={(e) => e.stopPropagation()}>
            <button onClick={() => setShowContact(false)} className="absolute top-4 right-4 text-zinc-400 hover:text-zinc-700 transition-colors">
              <X className="w-5 h-5" />
            </button>

            <h2 className="text-lg font-semibold mb-1">Contact</h2>
            <p className="text-sm text-zinc-500 mb-6">Une question ou un retour ? Envoyez-moi un message.</p>

            {contactSent ? (
              <div className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 p-4 rounded-sm">
                Message envoyé avec succès. Merci !
              </div>
            ) : (
              <form onSubmit={handleContactSubmit} className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-zinc-700 mb-1">Email</label>
                  <input
                    type="email"
                    name="email"
                    required
                    className="w-full h-10 px-3 border border-zinc-300 rounded-sm text-sm outline-none focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 transition-all"
                    placeholder="votre@email.ch"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-zinc-700 mb-1">Message</label>
                  <textarea
                    name="message"
                    required
                    rows={4}
                    className="w-full px-3 py-2 border border-zinc-300 rounded-sm text-sm outline-none focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 transition-all resize-none"
                    placeholder="Votre message..."
                  />
                </div>
                <button
                  type="submit"
                  disabled={contactLoading}
                  className="w-full h-10 bg-zinc-900 text-white text-sm font-medium rounded-sm hover:bg-zinc-800 transition-colors disabled:opacity-50"
                >
                  {contactLoading ? "Envoi..." : "Envoyer"}
                </button>
              </form>
            )}
          </div>
        </div>
      )}

    </div>
  );
}