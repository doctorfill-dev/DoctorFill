import { useState, useEffect, useRef, DragEvent } from "react";
import JSZip from "jszip";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Loader2, FolderArchive, FileCheck, FileText, Trash2, ChevronRight, Server, Send, Bot, User } from "lucide-react";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8080";
const API_KEY = import.meta.env.VITE_API_KEY || "";

const apiFetch = (url: string, options: RequestInit = {}) => {
  const headers = new Headers(options.headers || {});
  if (API_KEY) headers.set("X-API-Key", API_KEY);
  return fetch(url, { ...options, headers });
};

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export default function App() {
  const [reports, setReports] = useState<File[]>([]);
  const [availableForms, setAvailableForms] = useState<string[]>([]);
  const [formId, setFormId] = useState<string>("");
  const [isLoading, setIsLoading] = useState(false);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string>("");
  const [progress, setProgress] = useState<number>(0);

  // Chat state
  const [jobId, setJobId] = useState<string | null>(null);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  useEffect(() => {
    const fetchForms = async () => {
      try {
        const res = await apiFetch(`${BASE_URL}/forms`);
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
      let allEntries: any[] = [];
      let batch: any[];
      do {
        batch = await new Promise<any[]>((resolve) => dirReader.readEntries(resolve));
        allEntries = [...allEntries, ...batch];
      } while (batch.length > 0);
      for (const child of allEntries) {
        const childFiles = await processEntry(child);
        foundFiles = [...foundFiles, ...childFiles];
      }
    }
    return foundFiles;
  };

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => { e.preventDefault(); setIsDragging(true); };
  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => { e.preventDefault(); setIsDragging(false); };

  const handleDrop = async (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    if (!e.dataTransfer.items) return;
    const entries: FileSystemEntry[] = [];
    for (const item of Array.from(e.dataTransfer.items)) {
      if (item.kind === "file") {
        const entry = item.webkitGetAsEntry();
        if (entry) entries.push(entry);
      }
    }
    let newFiles: File[] = [];
    for (const entry of entries) {
      const extracted = await processEntry(entry);
      newFiles = [...newFiles, ...extracted];
    }
    setReports((prev) => {
      const combined = [...prev, ...newFiles];
      return combined.filter((v, i, a) => a.findIndex((t) => t.name === v.name) === i);
    });
  };

  const pollStatus = async (jid: string, token: string) => {
    try {
      const res = await apiFetch(`${BASE_URL}/status/${jid}`);
      if (!res.ok) throw new Error("Impossible de lire le statut de la tâche.");
      const data = await res.json();
      setStatusMessage(data.message);
      setProgress(data.progress);
      if (data.status === "completed") {
        const pdfRes = await apiFetch(`${BASE_URL}/download/${jid}?token=${encodeURIComponent(token)}`);
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
        setTimeout(() => pollStatus(jid, token), 2000);
      }
    } catch (err: any) {
      setError(err.message || "Perte de connexion avec le serveur.");
      setIsLoading(false);
    }
  };

  const handleProcess = async () => {
    if (reports.length === 0 || !formId) { setError("Il manque le formulaire ou les rapports."); return; }
    setIsLoading(true);
    setError(null);
    setPdfUrl(null);
    setProgress(0);
    setStatusMessage("Initialisation de la connexion...");
    setChatMessages([]);
    setJobId(null);

    const formData = new FormData();
    formData.append("form_id", formId);
    reports.forEach((file) => formData.append("report_files", file));

    try {
      const response = await apiFetch(`${BASE_URL}/process-form`, { method: "POST", body: formData });
      if (!response.ok) {
        const errData = await response.json().catch(() => null);
        throw new Error(errData?.detail || `Erreur serveur : ${response.status}`);
      }
      const data = await response.json();
      if (data.job_id) {
        setJobId(data.job_id);
        pollStatus(data.job_id, data.token || "");
      } else {
        throw new Error("Job ID manquant dans la réponse.");
      }
    } catch (err: any) {
      setError(err.message || "Erreur lors du traitement.");
      setIsLoading(false);
    }
  };

  const handleChatSend = async () => {
    if (!chatInput.trim() || !jobId || chatLoading) return;

    const userMsg = chatInput.trim();
    setChatInput("");

    const newHistory = [...chatMessages, { role: "user" as const, content: userMsg }];
    setChatMessages([...newHistory, { role: "assistant" as const, content: "" }]);
    setChatLoading(true);

    try {
      const res = await apiFetch(`${BASE_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: jobId,
          message: userMsg,
          history: chatMessages.map((m) => ({ role: m.role, content: m.content })),
        }),
      });

      if (!res.ok || !res.body) throw new Error("Erreur de connexion au chatbot.");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // Split on both \r\n and \n for SSE compatibility
        const lines = buffer.split(/\r?\n/);
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith("data:")) continue;
          const payload = trimmed.slice(5).trim();
          if (!payload || payload === "[DONE]") continue;
          try {
            const parsed = JSON.parse(payload);
            const delta = parsed?.choices?.[0]?.delta?.content ?? "";
            if (delta) {
              setChatMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (!last) return prev;
                updated[updated.length - 1] = { ...last, content: last.content + delta };
                return updated;
              });
            }
          } catch { /* ignore malformed SSE lines */ }
        }
      }
    } catch (err: any) {
      setChatMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: "assistant",
          content: "Désolé, une erreur est survenue. Veuillez réessayer.",
        };
        return updated;
      });
    } finally {
      setChatLoading(false);
    }
  };

  const handleReset = () => {
    setReports([]);
    setPdfUrl(null);
    setError(null);
    setStatusMessage("");
    setProgress(0);
    setIsLoading(false);
    setChatMessages([]);
    setJobId(null);
    setChatInput("");
  };

  return (
    <div className="min-h-screen bg-[#FDFDFD] p-6 md:p-10 text-zinc-900 selection:bg-emerald-100 selection:text-emerald-900 font-sans">
      <div className="max-w-7xl mx-auto space-y-6">

        {/* HEADER */}
        <header className="flex flex-col md:flex-row md:items-center justify-between bg-white p-5 rounded-sm border border-zinc-200 gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-3">
              <img src="/logo.png" alt="DoctorFill" className="w-10 h-10 rounded-md shadow-sm border border-zinc-200" />
              doctorfill-dev.
            </h1>
            <div className="flex items-center gap-2 mt-1.5">
              <Server className="w-3.5 h-3.5 text-zinc-400" />
              <p className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Nvidia DGX Spark // Gen-XFA</p>
            </div>
          </div>
          <div className="flex items-center gap-3 bg-zinc-50/50 p-1.5 rounded-sm border border-zinc-200">
            <label className="text-xs font-mono text-zinc-500 uppercase tracking-wider pl-3">Cible :</label>
            <select
              value={formId}
              onChange={(e) => setFormId(e.target.value)}
              className="h-9 w-48 rounded-sm border-zinc-300 bg-white px-3 py-1 text-sm font-medium shadow-none outline-none focus:ring-1 focus:ring-emerald-500 border transition-all"
            >
              {availableForms.length === 0 && <option disabled>Connexion API...</option>}
              {availableForms.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          </div>
        </header>

        {/* MAIN GRID */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">

          {/* LEFT — INPUTS */}
          <div className="lg:col-span-5 flex flex-col gap-6">
            <Card className="flex-1 shadow-none rounded-sm border-zinc-200 flex flex-col bg-white">
              <CardHeader className="pb-3 border-b border-zinc-100 mb-4">
                <CardTitle className="text-base font-semibold">Sources de données</CardTitle>
              </CardHeader>
              <CardContent className="flex-1 flex flex-col gap-4">
                <div
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                  className={`flex-1 flex flex-col items-center justify-center border border-dashed rounded-sm transition-all duration-200 p-8 text-center min-h-[200px]
                    ${isDragging ? "border-emerald-500 bg-emerald-50/50 scale-[1.02]" : "border-zinc-300 bg-zinc-50/50 hover:bg-zinc-100/50"}`}
                >
                  <FolderArchive className={`w-10 h-10 mb-4 transition-colors ${isDragging ? "text-emerald-600" : "text-zinc-400"}`} strokeWidth={1.5} />
                  <h3 className="font-semibold text-zinc-800 text-sm mb-1">Dépôt sécurisé</h3>
                  <p className="text-xs text-zinc-500 max-w-[250px] leading-relaxed">Glissez vos dossiers, archives ZIP ou PDF. Traitement local strict.</p>
                </div>

                {reports.length > 0 && (
                  <div className="bg-white border border-zinc-200 rounded-sm p-3 flex flex-col max-h-[220px]">
                    <div className="flex justify-between items-center mb-2 pb-2 border-b border-zinc-100">
                      <span className="text-xs font-semibold text-zinc-700">{reports.length} document(s) en file d'attente</span>
                      <button onClick={handleReset} className="text-[10px] text-red-600 hover:text-red-700 flex items-center font-medium uppercase tracking-wider bg-red-50 px-2 py-1 rounded-sm transition-colors">
                        <Trash2 className="w-3 h-3 mr-1" /> Purger
                      </button>
                    </div>
                    <div className="overflow-y-auto space-y-1 pr-1 custom-scrollbar">
                      {reports.map((f, i) => (
                        <div key={i} className="text-xs text-zinc-600 truncate flex items-center p-2 bg-zinc-50 border border-zinc-100 rounded-sm">
                          <FileText className="w-3.5 h-3.5 mr-2 text-zinc-400 shrink-0" />
                          {f.name}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {error && (
                  <div className="text-sm text-red-700 font-medium bg-red-50 border border-red-200 p-3 rounded-sm flex items-start">
                    <span className="mr-2">⚠️</span> {error}
                  </div>
                )}

                <div className="space-y-3 mt-2 pt-4 border-t border-zinc-100">
                  <Button
                    onClick={handleProcess}
                    disabled={isLoading || reports.length === 0}
                    className="w-full bg-zinc-900 hover:bg-zinc-800 text-white font-medium rounded-sm h-11 text-sm transition-all relative overflow-hidden disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isLoading && (
                      <div className="absolute top-0 left-0 h-full bg-emerald-600 transition-all duration-500 ease-out" style={{ width: `${progress}%` }} />
                    )}
                    {isLoading ? (
                      <span className="relative z-10 flex items-center">
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Traitement asynchrone... {progress}%
                      </span>
                    ) : (
                      <span className="relative z-10 flex items-center">
                        Exécuter la pipeline <ChevronRight className="ml-2 h-4 w-4" />
                      </span>
                    )}
                  </Button>
                  {isLoading && statusMessage && (
                    <div className="flex items-center justify-center gap-2 text-xs font-mono text-zinc-500 bg-zinc-50 border border-zinc-200 py-2 rounded-sm">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                      {statusMessage}
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>

          {/* RIGHT — PDF VIEWER */}
          <div className="lg:col-span-7">
            <Card className="h-[750px] flex flex-col shadow-none border-zinc-200 rounded-sm overflow-hidden bg-white">
              <CardHeader className="bg-zinc-50/50 border-b border-zinc-200 py-3 flex flex-row items-center justify-between space-y-0">
                <CardTitle className="text-sm font-semibold text-zinc-800">Visualiseur XFA</CardTitle>
                {pdfUrl && (
                  <a href={pdfUrl} download={`Final_${formId}.pdf`}>
                    <Button variant="outline" size="sm" className="h-8 rounded-sm border-zinc-300 bg-white text-xs font-medium hover:bg-zinc-50 hover:text-zinc-900">
                      Télécharger
                    </Button>
                  </a>
                )}
              </CardHeader>
              <CardContent className="flex-1 flex flex-col items-center justify-center p-0 bg-zinc-100 relative">
                {pdfUrl ? (
                  <iframe src={pdfUrl} className="w-full h-full border-0" title="PDF Result" />
                ) : (
                  <div className="text-zinc-400 flex flex-col items-center space-y-4">
                    <div className="w-16 h-16 rounded-sm border border-zinc-200 bg-white shadow-sm flex items-center justify-center">
                      <FileCheck className="w-8 h-8 text-zinc-300" strokeWidth={1.5} />
                    </div>
                    <p className="text-xs font-medium tracking-wide uppercase text-zinc-400">En attente de génération</p>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>

        {/* CHAT PANEL — visible once form is generated */}
        {pdfUrl && jobId && (
          <Card className="shadow-none rounded-sm border-zinc-200 bg-white">
            <CardHeader className="border-b border-zinc-100 py-3 flex flex-row items-center gap-3 space-y-0">
              <div className="w-7 h-7 rounded-sm bg-emerald-50 border border-emerald-200 flex items-center justify-center shrink-0">
                <Bot className="w-4 h-4 text-emerald-600" />
              </div>
              <div>
                <CardTitle className="text-sm font-semibold">Assistant médical</CardTitle>
                <p className="text-xs text-zinc-500 mt-0.5">Posez vos questions sur le dossier traité</p>
              </div>
            </CardHeader>
            <CardContent className="p-0 flex flex-col">

              {/* Messages */}
              <div className="flex flex-col gap-4 p-5 min-h-[200px] max-h-[500px] overflow-y-auto custom-scrollbar">
                {chatMessages.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-10 text-zinc-400 gap-3">
                    <Bot className="w-8 h-8" strokeWidth={1.5} />
                    <p className="text-sm text-center max-w-sm leading-relaxed">
                      Le dossier médical est chargé. Vous pouvez poser des questions sur les diagnostics, les périodes d'incapacité, les traitements, etc.
                    </p>
                  </div>
                ) : (
                  chatMessages.map((msg, i) => (
                    <div key={i} className={`flex gap-3 ${msg.role === "user" ? "flex-row-reverse" : "flex-row"}`}>
                      <div className={`w-7 h-7 rounded-sm shrink-0 flex items-center justify-center border ${
                        msg.role === "user"
                          ? "bg-zinc-900 border-zinc-700"
                          : "bg-emerald-50 border-emerald-200"
                      }`}>
                        {msg.role === "user"
                          ? <User className="w-3.5 h-3.5 text-white" />
                          : <Bot className="w-3.5 h-3.5 text-emerald-600" />
                        }
                      </div>
                      <div className={`max-w-[80%] rounded-sm px-4 py-2.5 text-sm leading-relaxed border ${
                        msg.role === "user"
                          ? "bg-zinc-900 text-white border-zinc-700"
                          : "bg-zinc-50 text-zinc-800 border-zinc-200"
                      }`}>
                        {msg.content || (
                          <span className="flex items-center gap-1.5 text-zinc-400">
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            Analyse en cours...
                          </span>
                        )}
                      </div>
                    </div>
                  ))
                )}
                <div ref={chatEndRef} />
              </div>

              {/* Input */}
              <div className="border-t border-zinc-100 p-4 flex gap-3">
                <input
                  type="text"
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleChatSend(); } }}
                  placeholder="Ex: Quels sont tous les diagnostics du patient ?"
                  disabled={chatLoading}
                  className="flex-1 h-10 px-3 text-sm rounded-sm border border-zinc-300 bg-white outline-none focus:ring-1 focus:ring-emerald-500 disabled:opacity-50 transition-all placeholder:text-zinc-400"
                />
                <Button
                  onClick={handleChatSend}
                  disabled={chatLoading || !chatInput.trim()}
                  className="h-10 px-4 bg-zinc-900 hover:bg-zinc-800 text-white rounded-sm text-sm font-medium disabled:opacity-50"
                >
                  {chatLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                </Button>
              </div>

            </CardContent>
          </Card>
        )}

      </div>
    </div>
  );
}
