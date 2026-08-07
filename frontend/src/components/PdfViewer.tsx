import { useEffect, useRef, useState } from "react";
import * as pdfjsLib from "pdfjs-dist";
import { AnnotationMode } from "pdfjs-dist";
import type { PDFDocumentProxy } from "pdfjs-dist";
import { Loader2, ChevronLeft, ChevronRight, AlertTriangle } from "lucide-react";

// Le worker est servi depuis le bundle : pas de CDN, ce qui est nécessaire
// derrière la CSP de Tauri comme en déploiement Cloudflare Pages.
pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url
).toString();

// Le rendu se fait à cette échelle puis est réduit en CSS : sans ça le texte
// des champs est crénelé sur écran haute densité.
const RENDER_SCALE = 2;

interface PdfViewerProps {
  /** Blob URL du PDF rempli. */
  url: string;
}

/**
 * Liseuse PDF interne.
 *
 * Remplace l'<iframe> qui déléguait au lecteur natif du navigateur. Trois
 * raisons : le lecteur natif est absent de la webview Tauri, il refuse les
 * URL blob: dans certains contextes, et son rendu des champs de formulaire
 * varie d'un moteur à l'autre. pdf.js rend explicitement la couche AcroForm,
 * celle que le backend remplit.
 */
export function PdfViewer({ url }: PdfViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const docRef = useRef<PDFDocumentProxy | null>(null);
  // Un rendu pdf.js ne peut pas être concurrent sur le même canvas : on garde
  // la tâche en cours pour l'annuler si l'utilisateur change vite de page.
  const taskRef = useRef<{ cancel: () => void } | null>(null);

  const [pageCount, setPageCount] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Chargement du document
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setPage(1);

    const task = pdfjsLib.getDocument({
      url,
      // On rend la couche AcroForm, pas le XFA : c'est elle que l'orchestrateur
      // remplit et pour laquelle il génère les apparences.
      enableXfa: false,
      isEvalSupported: false,
    });

    task.promise
      .then((doc) => {
        if (cancelled) {
          doc.destroy();
          return;
        }
        docRef.current = doc;
        setPageCount(doc.numPages);
      })
      .catch((err) => {
        if (!cancelled) setError(err?.message ?? "PDF illisible.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      taskRef.current?.cancel();
      docRef.current?.destroy();
      docRef.current = null;
    };
  }, [url]);

  // Rendu de la page courante
  useEffect(() => {
    const doc = docRef.current;
    const canvas = canvasRef.current;
    if (!doc || !canvas || pageCount === 0) return;

    let cancelled = false;
    taskRef.current?.cancel();

    doc.getPage(page).then((pdfPage) => {
      if (cancelled) return;
      const viewport = pdfPage.getViewport({ scale: RENDER_SCALE });
      const context = canvas.getContext("2d");
      if (!context) return;

      canvas.width = viewport.width;
      canvas.height = viewport.height;

      const task = pdfPage.render({
        canvasContext: context,
        viewport,
        // ENABLE, et surtout pas ENABLE_FORMS : ce dernier retire les champs du
        // canvas pour les confier à la couche DOM interactive de pdf.js, que
        // cette liseuse en lecture seule ne monte pas — les champs seraient
        // vides. ENABLE peint les flux /AP, que l'orchestrateur génère.
        annotationMode: AnnotationMode.ENABLE,
      });
      taskRef.current = task;
      task.promise.catch((err: unknown) => {
        // Une annulation volontaire n'est pas une erreur à afficher.
        if (!cancelled && (err as { name?: string })?.name !== "RenderingCancelledException") {
          setError("Erreur de rendu de la page.");
        }
      });
    });

    return () => {
      cancelled = true;
    };
  }, [page, pageCount]);

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-zinc-500 space-y-2 p-6">
        <AlertTriangle className="w-6 h-6 text-amber-500" strokeWidth={1.5} />
        <p className="text-xs text-center">{error}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full w-full">
      <div className="flex-1 overflow-auto flex justify-center p-4">
        {loading ? (
          <div className="flex items-center text-zinc-400">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />
            <span className="text-xs">Chargement du document…</span>
          </div>
        ) : (
          <canvas
            ref={canvasRef}
            className="max-w-full h-auto shadow-sm border border-zinc-200 bg-white"
          />
        )}
      </div>

      {pageCount > 1 && (
        <div className="flex items-center justify-center gap-3 border-t border-zinc-200 bg-white py-2">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="p-1 rounded-sm text-zinc-600 hover:bg-zinc-100 disabled:opacity-30"
            aria-label="Page précédente"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="text-xs tabular-nums text-zinc-600">
            {page} / {pageCount}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
            disabled={page >= pageCount}
            className="p-1 rounded-sm text-zinc-600 hover:bg-zinc-100 disabled:opacity-30"
            aria-label="Page suivante"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  );
}
