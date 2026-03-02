"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import Link from "next/link";
import DocumentModal from "@/components/DocumentModal";
import PromoteModal from "@/components/PromoteModal";
import ValidationReportModal from "@/components/ValidationReportModal";
import AssignmentModal from "@/components/AssignmentModal";

// ── Toast System ──
type ToastType = "success" | "error" | "info";
function useToast() {
  const [toasts, setToasts] = useState<{ id: number; msg: string; type: ToastType }[]>([]);
  const counter = useRef(0);
  const show = useCallback((msg: string, type: ToastType = "info") => {
    const id = ++counter.current;
    setToasts(t => [...t, { id, msg, type }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 4000);
  }, []);
  return { toasts, show };
}

// ── Compliance helpers ──
function getStatusLabel(status: string) {
  if (!status || status === "none") return { label: "Not Checked", cls: "badge-none", icon: "○" };
  if (status === "COMPLIANT" || status === "PASS") return { label: "Compliant", cls: "badge-compliant", icon: "✓" };
  if (status === "NON_COMPLIANT" || status === "FAIL") return { label: "Non-Compliant", cls: "badge-non-compliant", icon: "✗" };
  if (status === "PENDING") return { label: "Validating...", cls: "badge-checking", icon: "↻" };
  return { label: status, cls: "badge-checking", icon: "↻" };
}

function getCardClass(status: string) {
  if (status === "COMPLIANT" || status === "PASS") return "card-compliant";
  if (status === "NON_COMPLIANT" || status === "FAIL") return "card-failed";
  if (status && status !== "none") return "card-checking";
  return "";
}

export default function Home() {
  const [folders, setFolders] = useState<any[]>([]);
  const [documents, setDocuments] = useState<any[]>([]);
  const [standards, setStandards] = useState<any[]>([]);
  const [docValidations, setDocValidations] = useState<Record<string, any>>({});
  const [folderStandards, setFolderStandards] = useState<Record<string, any>>({});
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const [newFolderName, setNewFolderName] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Modals
  const [viewingDoc, setViewingDoc] = useState<{ doc: any; tab: "original" | "fixed" } | null>(null);
  const [promotingDoc, setPromotingDoc] = useState<any | null>(null);
  const [checkingDoc, setCheckingDoc] = useState<{ report: any; filename: string; docId: string } | null>(null);
  const [assigningDoc, setAssigningDoc] = useState<{ type: "FOLDER" | "DOCUMENT"; id: string; name: string } | null>(null);
  const [fixingDocId, setFixingDocId] = useState<string | null>(null);
  const [applyingDocId, setApplyingDocId] = useState<string | null>(null);
  const [applyStandardModal, setApplyStandardModal] = useState<any | null>(null);

  const { toasts, show: showToast } = useToast();

  const loadData = useCallback(async () => {
    try {
      const [f, d, s] = await Promise.all([api.getFolders(), api.getDocuments(), api.getStandards()]);
      setFolders(f);
      setDocuments(d);
      setStandards(s);
      // Load folder standard assignments
      const fsMap: Record<string, any> = {};
      await Promise.allSettled(
        f.map(async (folder: any) => {
          try {
            const fs = await api.getFolderStandard(undefined, folder.id);
            if (fs.assigned) fsMap[folder.id] = fs.standard;
          } catch { }
        })
      );
      setFolderStandards(fsMap);
    } catch (e) {
      console.error(e);
    }
  }, []);

  // Load validations for visible documents
  const loadValidations = useCallback(async (docs: any[]) => {
    const updates: Record<string, any> = {};
    await Promise.allSettled(
      docs.map(async (d) => {
        try {
          const v = await api.getDocumentValidation(undefined, d.id);
          updates[d.id] = v;
        } catch { }
      })
    );
    setDocValidations(prev => ({ ...prev, ...updates }));
  }, []);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 8000);
    return () => clearInterval(interval);
  }, [loadData]);

  useEffect(() => {
    if (documents.length > 0) {
      loadValidations(documents);
      const iv = setInterval(() => loadValidations(documents), 8000);
      return () => clearInterval(iv);
    }
  }, [documents.length]);

  const handleCreateFolder = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newFolderName.trim()) return;
    try {
      await api.createFolder(undefined, { name: newFolderName, parent_id: selectedFolder });
      setNewFolderName("");
      showToast(`Folder "${newFolderName}" created`, "success");
      loadData();
    } catch {
      showToast("Failed to create folder", "error");
    }
  };

  const handleFileChange = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setIsUploading(true);
    try {
      for (const file of Array.from(files)) {
        const formData = new FormData();
        formData.append("file", file);
        if (selectedFolder) formData.append("folder_id", selectedFolder);
        await api.uploadDocument(undefined, formData);
        showToast(`"${file.name}" uploaded`, "success");
      }
      loadData();
    } catch (e: any) {
      showToast(`Upload failed: ${e.message}`, "error");
    } finally {
      setIsUploading(false);
    }
  };

  const handleCheck = async (doc: any) => {
    try {
      const report = await api.getDocumentValidation(undefined, doc.id);
      if (!report || report.status === "none") {
        showToast("No validation result. Apply a standard first.", "info");
      } else {
        setCheckingDoc({ report, filename: doc.filename, docId: doc.id });
        setDocValidations(prev => ({ ...prev, [doc.id]: report }));
      }
    } catch {
      showToast("Failed to fetch validation report", "error");
    }
  };

  const handleApplyStandard = (doc: any) => {
    if (standards.length === 0) {
      showToast("No standards available. Create or promote a standard first.", "info");
      return;
    }
    setApplyStandardModal(doc);
  };

  const handleApplyConfirm = async (doc: any, standardId: string) => {
    setApplyingDocId(doc.id);
    setApplyStandardModal(null);
    try {
      await api.applyStandardToDocument(undefined, standardId, doc.id);
      showToast(`Standard applied to "${doc.filename}"`, "success");
      setTimeout(() => loadValidations([doc]), 1000);
    } catch (e: any) {
      showToast(`Apply failed: ${e.message}`, "error");
    } finally {
      setApplyingDocId(null);
    }
  };

  const handleFix = async (doc: any) => {
    setFixingDocId(doc.id);
    try {
      const result = await api.fixDocument(undefined, doc.id);
      showToast(`"${doc.filename}" auto-fixed by AI!`, "success");
      setViewingDoc({ doc, tab: "fixed" });
      await loadValidations([doc]);
    } catch (e: any) {
      showToast(`Fix failed: ${e.message}`, "error");
    } finally {
      setFixingDocId(null);
    }
  };

  const handleDeleteDocument = async (doc: any) => {
    if (!confirm(`Are you sure you want to delete "${doc.filename}"?`)) return;
    try {
      await api.deleteDocument(undefined, doc.id);
      showToast(`"${doc.filename}" deleted`, "success");
      loadData();
    } catch (e: any) {
      showToast(`Delete failed: ${e.message}`, "error");
    }
  };

  const handleRenameDocument = async (doc: any) => {
    const newName = prompt("Enter new filename:", doc.filename);
    if (!newName || newName === doc.filename) return;
    try {
      await api.renameDocument(undefined, doc.id, newName);
      showToast(`"${doc.filename}" renamed to "${newName}"`, "success");
      loadData();
    } catch (e: any) {
      showToast(`Rename failed: ${e.message}`, "error");
    }
  };

  const handleDeleteFolder = async (folder: any) => {
    if (!confirm(`Are you sure you want to delete folder "${folder.name}" and ALL its content?`)) return;
    try {
      await api.deleteFolder(undefined, folder.id);
      showToast(`Folder "${folder.name}" deleted`, "success");
      if (selectedFolder === folder.id) setSelectedFolder(null);
      loadData();
    } catch (e: any) {
      showToast(`Delete failed: ${e.message}`, "error");
    }
  };

  const handleRenameFolder = async (folder: any) => {
    const newName = prompt("Enter new folder name:", folder.name);
    if (!newName || newName === folder.name) return;
    try {
      await api.renameFolder(undefined, folder.id, newName);
      showToast(`Folder "${folder.name}" renamed to "${newName}"`, "success");
      loadData();
    } catch (e: any) {
      showToast(`Rename failed: ${e.message}`, "error");
    }
  };


  const visibleDocs = documents
    .filter(d => d.folder_id === selectedFolder)
    .filter(d => !searchQuery || d.filename.toLowerCase().includes(searchQuery.toLowerCase()));

  return (
    <main>
      {/* ── App Header ── */}
      <div className="app-header">
        <div>
          <h1>DocAligner</h1>
          <p style={{ color: "var(--text-secondary)", fontSize: "0.875rem", marginTop: "0.25rem" }}>
            Extract, Apply & Enforce Document Standards with AI
          </p>
        </div>
        <div className="header-nav">
          <Link href="/standards" className="btn btn-outline">📋 Standards</Link>
          <Link href="/audit" className="btn btn-outline">📜 Audit Logs</Link>
        </div>
      </div>

      <div className="grid-layout">
        {/* ── Left Sidebar ── */}
        <aside>
          {/* Upload */}
          <div className="glass-card">
            <h3 style={{ marginBottom: "1rem" }}>📁 Upload Document</h3>
            <div
              className={`upload-area ${dragOver ? "drag-over" : ""}`}
              onClick={() => fileInputRef.current?.click()}
              onDragOver={e => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={e => { e.preventDefault(); setDragOver(false); handleFileChange(e.dataTransfer.files); }}
            >
              <div style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>
                {isUploading ? "⏳" : "⬆"}
              </div>
              <div style={{ fontSize: "0.85rem", color: "var(--text-secondary)" }}>
                {isUploading ? "Uploading…" : "Drop files here or click to browse"}
              </div>
              <div style={{ fontSize: "0.72rem", color: "var(--text-muted)", marginTop: "0.4rem" }}>
                .odt .ods .odp .pdf .doc .docx .txt
              </div>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                style={{ display: "none" }}
                accept=".odt,.ods,.odp,.pdf,.doc,.docx,.txt"
                onChange={e => handleFileChange(e.target.files)}
              />
            </div>
          </div>

          {/* New Folder */}
          <div className="glass-card">
            <h3 style={{ marginBottom: "1rem" }}>🗂 New Folder</h3>
            <form onSubmit={handleCreateFolder}>
              <div className="form-group">
                <input
                  type="text"
                  placeholder="Folder name…"
                  value={newFolderName}
                  onChange={e => setNewFolderName(e.target.value)}
                />
              </div>
              <button type="submit" className="btn btn-primary" style={{ width: "100%" }}>
                Create Folder
              </button>
            </form>
          </div>

          {/* Folder Tree */}
          <div className="glass-card">
            <h3 style={{ marginBottom: "0.75rem" }}>📂 Folders</h3>
            <div
              className={`folder-item ${selectedFolder === null ? "active" : ""}`}
              onClick={() => setSelectedFolder(null)}
            >
              <span>📁 Root</span>
              <span style={{ fontSize: "0.7rem", color: "var(--text-secondary)" }}>
                {documents.filter(d => d.folder_id === null).length} files
              </span>
            </div>
            {folders.map(f => (
              <div
                key={f.id}
                className={`folder-item ${selectedFolder === f.id ? "active" : ""}`}
                onClick={() => setSelectedFolder(f.id)}
                style={{ position: "relative" }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                    <span>📁 {f.name}</span>
                    <button
                      className="btn-icon-subtle"
                      onClick={e => { e.stopPropagation(); handleRenameFolder(f); }}
                      title="Rename folder"
                    >✏️</button>
                    <button
                      className="btn-icon-subtle danger"
                      onClick={e => { e.stopPropagation(); handleDeleteFolder(f); }}
                      title="Delete folder and contents"
                    >🗑️</button>
                  </div>
                  {folderStandards[f.id] && (
                    <div style={{ fontSize: "0.65rem", color: "#a5b4fc", marginTop: "0.15rem", paddingLeft: "1.2rem" }}>
                      ⚡ {folderStandards[f.id].name} v{folderStandards[f.id].version_number}
                    </div>
                  )}
                </div>
                <div style={{ display: "flex", gap: "0.4rem", alignItems: "center", flexShrink: 0 }}>
                  <span style={{ fontSize: "0.7rem", color: "var(--text-secondary)" }}>
                    {documents.filter(d => d.folder_id === f.id).length}
                  </span>
                  <button
                    className="btn btn-sm btn-outline"
                    onClick={e => { e.stopPropagation(); setAssigningDoc({ type: "FOLDER", id: f.id, name: f.name }); }}
                  >Assign</button>
                </div>
              </div>
            ))}

          </div>

          {/* Standards summary */}
          {standards.length > 0 && (
            <div className="glass-card">
              <h3 style={{ marginBottom: "0.75rem" }}>⚡ Active Standards</h3>
              {standards.map(s => (
                <div key={s.id} style={{ padding: "0.5rem 0", borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
                  <div style={{ fontSize: "0.85rem", fontWeight: 600 }}>{s.name}</div>
                  <div style={{ fontSize: "0.7rem", color: "var(--text-secondary)" }}>
                    {s.versions?.length || 0} version{s.versions?.length !== 1 ? "s" : ""}
                  </div>
                </div>
              ))}
            </div>
          )}
        </aside>

        {/* ── Main Content ── */}
        <section>
          <div className="glass-card">
            {/* Header */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem" }}>
              <div>
                <h2>Documents</h2>
                <div style={{ fontSize: "0.8rem", color: "var(--text-secondary)", marginTop: "0.2rem" }}>
                  {selectedFolder ? `📁 ${folders.find(f => f.id === selectedFolder)?.name}` : "📁 Root"} · {visibleDocs.length} files
                </div>
              </div>
              <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                <span style={{ fontSize: "0.75rem", color: "var(--text-secondary)" }}>
                  {Object.values(docValidations).filter((v: any) => v?.status === "COMPLIANT").length} compliant of {visibleDocs.length}
                </span>
              </div>
            </div>

            {/* Search */}
            <div className="search-bar">
              <span style={{ color: "var(--text-secondary)" }}>🔍</span>
              <input
                placeholder="Search documents…"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
              />
            </div>

            {/* Document Cards */}
            {visibleDocs.length > 0 ? (
              <div className="doc-grid">
                {visibleDocs.map(doc => {
                  const v = docValidations[doc.id];
                  const status = v?.status || "none";
                  const score = v?.report?.score;
                  const statusInfo = getStatusLabel(status);
                  const cardCls = getCardClass(status);
                  const isFixing = fixingDocId === doc.id;
                  const isApplying = applyingDocId === doc.id;

                  return (
                    <div key={doc.id} className={`doc-card ${cardCls} fade-in ${["NON_COMPLIANT", "FAIL", "PENDING"].includes(status) ? "checking-pulse" : ""}`}>
                      {/* Card Header */}
                      <div className="doc-card-header">
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                            <div className="doc-filename" style={{ flex: 1 }}>
                              {doc.filename.length > 30 ? doc.filename.substring(0, 28) + "…" : doc.filename}
                            </div>
                            <button className="btn-icon-subtle" onClick={() => handleRenameDocument(doc)} title="Rename">✏️</button>
                            <button className="btn-icon-subtle danger" onClick={() => handleDeleteDocument(doc)} title="Delete">🗑️</button>
                          </div>
                          <div className="doc-meta">{doc.id.substring(0, 16)}…</div>
                        </div>
                        <span className={`status-badge ${statusInfo.cls}`}>
                          {statusInfo.icon} {statusInfo.label}
                        </span>
                      </div>


                      {/* Score bar */}
                      {score !== undefined && (
                        <div className="score-bar-wrap">
                          <div className="score-bar-track">
                            <div
                              className="score-bar-fill"
                              style={{
                                width: `${score}%`,
                                background: score >= 70 ? "linear-gradient(90deg, #10b981, #34d399)" :
                                  score >= 40 ? "linear-gradient(90deg, #f59e0b, #fbbf24)" :
                                    "linear-gradient(90deg, #ef4444, #f87171)"
                              }}
                            />
                          </div>
                          <span className="score-label">{score.toFixed(0)}%</span>
                        </div>
                      )}

                      {/* Actions */}
                      <div className="doc-card-actions">
                        {/* View Original */}
                        <button
                          className="btn btn-sm btn-info"
                          onClick={() => setViewingDoc({ doc, tab: "original" })}
                          title="View document content"
                        >
                          👁 View
                        </button>

                        {/* Promote to Standard */}
                        <button
                          className="btn btn-sm btn-outline"
                          onClick={() => setPromotingDoc(doc)}
                          title="Promote this document as a standard template"
                        >
                          ⬆ Promote
                        </button>

                        {/* Apply Standard */}
                        <button
                          className="btn btn-sm btn-warning"
                          onClick={() => handleApplyStandard(doc)}
                          disabled={isApplying}
                          title="Apply a standard to this document"
                        >
                          {isApplying ? "⏳" : "📋"} Apply Std
                        </button>

                        {/* Check Compliance */}
                        <button
                          className="btn btn-sm btn-outline"
                          onClick={() => handleCheck(doc)}
                          title="View compliance report"
                        >
                          ✅ Check
                        </button>

                        {/* Auto-Fix (only if non-compliant) */}
                        <button
                          className="btn btn-sm btn-danger"
                          onClick={() => handleFix(doc)}
                          disabled={isFixing}
                          title="AI auto-fix document to comply with standard"
                        >
                          {isFixing ? "⏳ Fixing…" : "🔧 Auto-Fix"}
                        </button>

                        {/* View Fixed (if available) */}
                        {v?.report?.fixed_content && (
                          <button
                            className="btn btn-sm btn-success"
                            onClick={() => setViewingDoc({ doc, tab: "fixed" })}
                            title="View AI-fixed version"
                          >
                            ✨ Fixed Version
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div style={{
                display: "flex", flexDirection: "column", alignItems: "center",
                justifyContent: "center", padding: "4rem 2rem",
                color: "var(--text-secondary)", textAlign: "center"
              }}>
                <div style={{ fontSize: "3rem", marginBottom: "1rem" }}>📭</div>
                <h3 style={{ color: "var(--text-secondary)", marginBottom: "0.5rem" }}>No documents here</h3>
                <p style={{ fontSize: "0.875rem" }}>
                  Upload documents using the panel on the left.
                </p>
              </div>
            )}
          </div>
        </section>
      </div>

      {/* ── Apply Standard Picker ── */}
      {applyStandardModal && (
        <ApplyStandardPicker
          doc={applyStandardModal}
          standards={standards}
          onConfirm={handleApplyConfirm}
          onClose={() => setApplyStandardModal(null)}
        />
      )}

      {/* ── Modals ── */}
      {viewingDoc && (
        <DocumentModal
          document={viewingDoc.doc}
          initialTab={viewingDoc.tab}
          onClose={() => setViewingDoc(null)}
        />
      )}
      {promotingDoc && (
        <PromoteModal
          document={promotingDoc}
          onClose={() => setPromotingDoc(null)}
          onSuccess={() => { loadData(); showToast("Document promoted to standard!", "success"); }}
        />
      )}
      {checkingDoc && (
        <ValidationReportModal
          report={checkingDoc.report}
          filename={checkingDoc.filename}
          documentId={checkingDoc.docId}
          onClose={() => setCheckingDoc(null)}
        />
      )}
      {assigningDoc && (
        <AssignmentModal
          type={assigningDoc.type}
          targetId={assigningDoc.id}
          targetName={assigningDoc.name}
          onClose={() => setAssigningDoc(null)}
          onSuccess={() => { loadData(); setAssigningDoc(null); showToast("Standard assigned!", "success"); }}
        />
      )}

      {/* ── Toasts ── */}
      <div className="toast-container">
        {toasts.map(t => (
          <div key={t.id} className={`toast toast-${t.type}`}>{t.msg}</div>
        ))}
      </div>
    </main>
  );
}

// ── Inline Apply Standard Picker ──
function ApplyStandardPicker({
  doc, standards, onConfirm, onClose
}: { doc: any; standards: any[]; onConfirm: (doc: any, stdId: string) => void; onClose: () => void }) {
  const [selectedId, setSelectedId] = useState(standards[0]?.id || "");

  return (
    <div className="modal-overlay" style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)", backdropFilter: "blur(8px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 2000 }} onClick={onClose}>
      <div style={{ background: "linear-gradient(135deg, #1e1b4b, #0f172a)", border: "1px solid rgba(99,102,241,0.3)", borderRadius: "1.25rem", padding: "2rem", width: "100%", maxWidth: "420px", boxShadow: "0 25px 60px rgba(0,0,0,0.6)" }} onClick={e => e.stopPropagation()}>
        <h3 style={{ marginBottom: "1rem", fontSize: "1rem" }}>📋 Apply Standard to "{doc.filename}"</h3>
        <p style={{ fontSize: "0.82rem", color: "#94a3b8", marginBottom: "1.25rem" }}>
          Applying a standard will run AI compliance checks on this document.
        </p>
        <select
          value={selectedId}
          onChange={e => setSelectedId(e.target.value)}
          style={{ width: "100%", background: "rgba(0,0,0,0.25)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "0.5rem", padding: "0.6rem 0.8rem", color: "#f8fafc", marginBottom: "1.5rem" }}
        >
          {standards.map(s => (
            <option key={s.id} value={s.id} style={{ background: "#1e1b4b" }}>
              {s.name} ({s.versions?.length || 0} versions)
            </option>
          ))}
        </select>
        <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}>
          <button onClick={onClose} style={{ background: "transparent", border: "1px solid rgba(255,255,255,0.15)", color: "#94a3b8", padding: "0.55rem 1.1rem", borderRadius: "0.5rem", cursor: "pointer" }}>Cancel</button>
          <button onClick={() => onConfirm(doc, selectedId)} disabled={!selectedId} style={{ background: "linear-gradient(135deg, #6366f1, #8b5cf6)", border: "none", color: "white", padding: "0.55rem 1.2rem", borderRadius: "0.5rem", cursor: "pointer", fontWeight: 600 }}>
            Apply & Check
          </button>
        </div>
      </div>
    </div>
  );
}
