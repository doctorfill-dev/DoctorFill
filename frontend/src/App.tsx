import { useState, useEffect, DragEvent } from "react";
import JSZip from "jszip";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Loader2, FolderArchive, FileCheck, FileText, Trash2, UploadCloud, ChevronRight } from "lucide-react";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8080";

export default function App() {
  const [reports, setReports] = useState<File[]>([]);
  const [availableForms, setAvailableForms] = useState<string[]>([]);
  const [formId, setFormId] = useState<string>("");
  const [isLoading, setIsLoading] = useState(false);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  // NOUVEAU : États pour le tracking asynchrone
  const [statusMessage, setStatusMessage] = useState<string>("");
  const [progress, setProgress] = useState<number>(0);

  // --- CHARGEMENT DES FORMULAIRES AU DÉMARRAGE ---
  useEffect(() => {
    const fetchForms = async () => {
      try {
        const res = await fetch(`${BASE_URL}/forms`);
        if (res.ok) {
          const data = await res.json();
          setAvailableForms(data.forms);
          if (data.forms.length > 0) setFormId(data.forms[0]);
        }
      } catch (err) {
        console.error("API injoignable", err);
      }
    };
    fetchForms();
  }, []);

  // --- LOGIQUE D'EXTRACTION (ZIP & DOSSIERS) ---
  const extractZipToPdfs = async (file: File): Promise<File[]> => {
    const extracted: File[] = [];
    const zip = new JSZip();
    try {
      const loadedZip = await zip.loadAsync(file);
      for (const [filename, zipEntry] of Object.entries(loadedZip.files)) {
        if (!zipEntry.dir && filename.toLowerCase().endsWith(".pdf")) {
          const blob = await zipEntry.async("blob");
          extracted.push(new File([blob], filename, { type: "application/pdf" }));
        }
      }
    } catch (e) {
      console.error(`Erreur ZIP sur ${file.name}`, e);
    }
    return extracted;
  };

  const processEntry = async (entry: any): Promise<File[]> => {
    let foundFiles: File[] = [];
    if (entry.isFile) {
      const file = await new Promise<File>((resolve) => entry.file(resolve));
      if (file.name.toLowerCase().endsWith(".zip")) {
        foundFiles = await extractZipToPdfs(file);
      } else if (file.name.toLowerCase().endsWith(".pdf")) {
        foundFiles.push(file);
      }
    } else if (entry.isDirectory) {
      const dirReader = entry.createReader();
      const entries = await new Promise<any[]>((resolve) => {
        dirReader.readEntries(resolve);
      });
      for (const child of entries) {
        const childFiles = await processEntry(child);
        foundFiles = [...foundFiles, ...childFiles];
      }
    }
    return foundFiles;
  };

  // --- DRAG & DROP ---
  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = async (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    if (!e.dataTransfer.items) return;

    let newFiles: File[] = [];
    const items = Array.from(e.dataTransfer.items);

    for (const item of items) {
      if (item.kind === "file") {
        const entry = item.webkitGetAsEntry();
        if (entry) {
          const extracted = await processEntry(entry);
          newFiles = [...newFiles, ...extracted];
        }
      }
    }

    setReports((prev) => {
      const combined = [...prev, ...newFiles];
      return combined.filter((v, i, a) => a.findIndex((t) => t.name === v.name) === i);
    });
  };

  // --- NOUVEAU : SYSTÈME DE POLLING (Vérification toutes les 2s) ---
  const pollStatus = async (jobId: string) => {
    try {
      const res = await fetch(`${BASE_URL}/status/${jobId}`);
      if (!res.ok) throw new Error("Impossible de lire le statut de la tâche.");

      const data = await res.json();

      // Mise à jour de l'UI avec les vraies données du backend
      setStatusMessage(data.message);
      setProgress(data.progress);

      if (data.status === "completed") {
        // Tâche finie ! On lance la requête pour télécharger le PDF final
        const pdfRes = await fetch(`${BASE_URL}/download/${jobId}`);
        if (!pdfRes.ok) throw new Error("Erreur lors de la récupération du PDF.");

        const blob = await pdfRes.blob();
        setPdfUrl(URL.createObjectURL(blob));
        setIsLoading(false);
        setStatusMessage("");
        setProgress(0);
      } else if (data.status === "failed") {
        setError(data.message);
        setIsLoading(false);
      } else {
        // Toujours en cours, on re-vérifie dans 2 secondes
        setTimeout(() => pollStatus(jobId), 2000);
      }
    } catch (err: any) {
      setError(err.message || "Perte de connexion avec le serveur.");
      setIsLoading(false);
    }
  };

  // --- LANCEMENT INITIAL ---
  const handleProcess = async () => {
    if (reports.length === 0 || !formId) {
      setError("Il manque le formulaire ou les rapports.");
      return;
    }

    setIsLoading(true);
    setError(null);
    setPdfUrl(null);
    setProgress(0);
    setStatusMessage("Envoi des fichiers au DGX...");

    const formData = new FormData();
    formData.append("form_id", formId);
    reports.forEach((file) => formData.append("report_files", file));

    try {
      // Étape 1 : On poste les fichiers et on reçoit un job_id instantanément
      const response = await fetch(`${BASE_URL}/process-form`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) throw new Error(`Erreur serveur : ${response.status}`);

      const data = await response.json();

      if (data.job_id) {
        // Étape 2 : On démarre le polling avec le job_id
        pollStatus(data.job_id);
      } else {
        throw new Error("Job ID manquant dans la réponse.");
      }
    } catch (err: any) {
      setError(err.message || "Erreur lors du traitement.");
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-100 p-6 md:p-10 text-slate-900">
      <div className="max-w-7xl mx-auto space-y-6">

        <header className="flex items-center justify-between bg-white p-6 rounded-xl shadow-sm border border-slate-200">
          <div>
            <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
              <UploadCloud className="w-7 h-7 text-blue-600" />
              DoctorFill
            </h1>
            <p className="text-sm text-slate-500 mt-1">Génération XFA via NVIDIA DGX Spark</p>
          </div>

          <div className="flex items-center gap-3 bg-slate-50 p-2 rounded-lg border border-slate-200">
            <label className="text-sm font-medium text-slate-600 pl-2">Template :</label>
            <select
              value={formId}
              onChange={(e) => setFormId(e.target.value)}
              className="h-9 w-48 rounded-md border-slate-300 bg-white px-3 py-1 text-sm font-medium shadow-sm outline-none focus:ring-2 focus:ring-blue-500 border"
            >
              {availableForms.length === 0 && <option disabled>Connexion API...</option>}
              {availableForms.map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </select>
          </div>
        </header>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          <div className="lg:col-span-5 flex flex-col gap-6">
            <Card className="flex-1 shadow-sm border-slate-200 flex flex-col">
              <CardHeader className="pb-2">
                <CardTitle className="text-lg">Contexte Patient</CardTitle>
              </CardHeader>
              <CardContent className="flex-1 flex flex-col gap-4">

                <div
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                  className={`flex-1 flex flex-col items-center justify-center border-2 border-dashed rounded-xl transition-all duration-200 p-8 text-center min-h-[200px]
                    ${isDragging ? "border-blue-500 bg-blue-50/50 scale-[1.02]" : "border-slate-300 bg-slate-50 hover:bg-slate-100"}
                  `}
                >
                  <FolderArchive className={`w-12 h-12 mb-4 transition-colors ${isDragging ? "text-blue-500" : "text-slate-400"}`} />
                  <h3 className="font-semibold text-slate-700 text-lg">Glissez vos dossiers ici</h3>
                  <p className="text-sm text-slate-500 mt-2 max-w-[250px]">
                    Dossiers entiers, archives .ZIP ou fichiers .PDF simples. L'application extrait le tout.
                  </p>
                </div>

                {reports.length > 0 && (
                  <div className="bg-white border border-slate-200 rounded-lg p-3 shadow-sm flex flex-col max-h-[200px]">
                    <div className="flex justify-between items-center mb-3 pb-2 border-b border-slate-100">
                      <span className="text-sm font-semibold text-slate-700">{reports.length} Document(s) extrait(s)</span>
                      <button onClick={() => setReports([])} className="text-xs text-red-500 hover:text-red-700 flex items-center font-medium bg-red-50 px-2 py-1 rounded">
                        <Trash2 className="w-3 h-3 mr-1" /> Vider
                      </button>
                    </div>
                    <div className="overflow-y-auto space-y-1.5 pr-2">
                      {reports.map((f, i) => (
                        <div key={i} className="text-xs text-slate-600 truncate flex items-center p-2 bg-slate-50 rounded hover:bg-slate-100 transition-colors">
                          <FileText className="w-3.5 h-3.5 mr-2 text-blue-500 shrink-0" />
                          {f.name}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {error && <div className="text-sm text-red-600 font-medium bg-red-50 border border-red-100 p-3 rounded-lg">{error}</div>}

                <div className="space-y-2 mt-2">
                  <Button
                    onClick={handleProcess}
                    disabled={isLoading || reports.length === 0}
                    className="w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold shadow-md h-12 text-base transition-all relative overflow-hidden"
                  >
                    {/* La VRAIE barre de progression connectée au Backend */}
                    {isLoading && (
                      <div
                        className="absolute top-0 left-0 h-full bg-blue-800 transition-all duration-500 ease-out"
                        style={{ width: `${progress}%` }}
                      />
                    )}

                    {isLoading ? (
                      <span className="relative z-10 flex items-center">
                        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                        Traitement en cours... {progress}%
                      </span>
                    ) : (
                      <span className="relative z-10 flex items-center">
                        Lancer l'automatisation <ChevronRight className="ml-2 h-5 w-5" />
                      </span>
                    )}
                  </Button>

                  {/* Message exact provenant du backend (OCR, Vectorisation, etc.) */}
                  {isLoading && statusMessage && (
                    <p className="text-xs text-center text-slate-500 font-medium animate-pulse">
                      {statusMessage}
                    </p>
                  )}
                </div>

              </CardContent>
            </Card>
          </div>

          <div className="lg:col-span-7">
            <Card className="h-[750px] flex flex-col shadow-sm border-slate-200 overflow-hidden">
              <CardHeader className="bg-slate-50 border-b border-slate-200 py-4 flex flex-row items-center justify-between space-y-0">
                <CardTitle className="text-lg">Prévisualisation du Formulaire</CardTitle>
                {pdfUrl && (
                  <a href={pdfUrl} download={`Final_${formId}.pdf`}>
                    <Button variant="outline" size="sm" className="h-8 border-slate-300 bg-white">
                      Télécharger le PDF
                    </Button>
                  </a>
                )}
              </CardHeader>
              <CardContent className="flex-1 flex flex-col items-center justify-center p-0 bg-slate-200/50 relative">
                {pdfUrl ? (
                  <iframe src={pdfUrl} className="w-full h-full border-0 shadow-inner" title="PDF Result" />
                ) : (
                  <div className="text-slate-400 flex flex-col items-center space-y-4">
                    <div className="w-20 h-20 rounded-full bg-slate-200/50 flex items-center justify-center">
                      <FileCheck className="w-10 h-10 text-slate-300" />
                    </div>
                    <p className="text-sm font-medium">Le document finalisé s'affichera ici.</p>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}