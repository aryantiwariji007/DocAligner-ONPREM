"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";

interface DocumentModalProps {
    document: any;
    initialTab?: "original" | "fixed";
    onClose: () => void;
}

export default function DocumentModal({ document, initialTab = "original", onClose }: DocumentModalProps) {
    const [activeTab, setActiveTab] = useState<"original" | "fixed">(initialTab);
    const [originalContent, setOriginalContent] = useState<string>("");
    const [fixedContent, setFixedContent] = useState<string>("");
    const [loadingOriginal, setLoadingOriginal] = useState(false);
    const [loadingFixed, setLoadingFixed] = useState(false);
    const [validationData, setValidationData] = useState<any>(null);

    useEffect(() => {
        loadOriginal();
        loadValidation();
    }, [document.id]);

    useEffect(() => {
        if (activeTab === "fixed" && !fixedContent) {
            loadFixedContent();
        }
    }, [activeTab]);

    useEffect(() => {
        let interval: NodeJS.Timeout;
        if (validationData?.status === "PENDING") {
            interval = setInterval(async () => {
                try {
                    const latest = await api.getDocumentValidation(undefined, document.id);
                    if (latest) {
                        setValidationData(latest);
                        if (latest.report?.fixed_content) {
                            setFixedContent(latest.report.fixed_content);
                        }
                        if (latest.status !== "PENDING") {
                            clearInterval(interval);
                        }
                    }
                } catch (e) {
                    console.error("Failed to poll validation status", e);
                }
            }, 3000);
        }
        return () => clearInterval(interval);
    }, [validationData?.status, document.id]);

    const loadOriginal = async () => {
        setLoadingOriginal(true);
        try {
            const data = await api.getDocumentContent(undefined, document.id);
            setOriginalContent(data.content);
        } catch (e) {
            setOriginalContent("Could not load document content.");
        } finally {
            setLoadingOriginal(false);
        }
    };

    const loadValidation = async () => {
        try {
            const data = await api.getDocumentValidation(undefined, document.id);
            setValidationData(data);
            if (data?.report?.fixed_content) {
                setFixedContent(data.report.fixed_content);
            }
        } catch (e) { }
    };

    const loadFixedContent = async () => {
        if (fixedContent) return;
        setLoadingFixed(true);
        try {
            const data = await api.fixDocument(undefined, document.id);
            if (data.status === "async_triggered") {
                // This triggers the useEffect polling
                setValidationData((prev: any) => ({ ...prev, status: "PENDING" }));
                return;
            }
            setFixedContent(data.fixed_content);
        } catch (e: any) {
            setFixedContent(`Auto-fix failed: ${e.response?.data?.detail || e.message || "Unknown error"}`);
        } finally {
            setLoadingFixed(false);
        }
    };

    const score = validationData?.report?.score;
    const isCompliant = validationData?.status === "COMPLIANT";
    const status = validationData?.status;

    return (
        <div className="doc-modal-overlay" onClick={onClose}>
            <div className="doc-modal" onClick={e => e.stopPropagation()}>
                {/* Header */}
                <div className="doc-modal-header">
                    <div>
                        <h2 style={{ fontSize: "1.1rem", fontWeight: 700 }}>📄 {document.filename}</h2>
                        <div style={{ display: "flex", gap: "0.75rem", marginTop: "0.5rem", alignItems: "center" }}>
                            {status && status !== "none" ? (
                                <span className={`badge ${isCompliant ? "badge-pass" : "badge-fail"}`}>
                                    {isCompliant ? "✓ Compliant" : "✗ Non-Compliant"}
                                </span>
                            ) : (
                                <span className="badge badge-none">○ Not Checked</span>
                            )}
                            {score !== undefined && (
                                <span className="badge badge-score">Score: {score.toFixed(0)}%</span>
                            )}
                        </div>
                    </div>
                    <button className="close-btn" onClick={onClose}>✕</button>
                </div>

                {/* Tabs */}
                <div className="doc-modal-tabs">
                    <button
                        className={`tab-btn ${activeTab === "original" ? "tab-active" : ""}`}
                        onClick={() => setActiveTab("original")}
                    >
                        📄 Original
                    </button>
                    <button
                        className={`tab-btn ${activeTab === "fixed" ? "tab-active" : ""}`}
                        onClick={() => setActiveTab("fixed")}
                    >
                        ✨ AI-Fixed Version
                    </button>
                </div>

                {/* Content Area */}
                <div className="doc-modal-body">
                    {activeTab === "original" ? (
                        <div className="content-pane">
                            {loadingOriginal ? (
                                <div className="loading-state">Loading content...</div>
                            ) : (
                                <pre className="content-text">{originalContent}</pre>
                            )}
                        </div>
                    ) : (
                        <div className="content-pane">
                            {loadingFixed ? (
                                <div className="loading-state">
                                    <div className="spinner" />
                                    <p>AI is transforming document...</p>
                                </div>
                            ) : (
                                <pre className="content-text fixed-text">{fixedContent}</pre>
                            )}
                        </div>
                    )}
                </div>

                {/* Footer with violations if non-compliant */}
                {validationData?.report?.errors && validationData.report.errors.length > 0 && (
                    <div className="doc-modal-footer">
                        <h4 style={{ color: "#f87171", marginBottom: "0.5rem", fontSize: "0.8rem", textTransform: "uppercase" }}>
                            ⚠ Violations Found
                        </h4>
                        <div className="violation-chips">
                            {validationData.report.errors.slice(0, 3).map((e: string, i: number) => (
                                <span key={i} className="violation-chip">{e.substring(0, 80)}{e.length > 80 ? "…" : ""}</span>
                            ))}
                            {validationData.report.errors.length > 3 && (
                                <span className="violation-chip">+{validationData.report.errors.length - 3} more</span>
                            )}
                        </div>
                    </div>
                )}
            </div>

            <style>{`
        .doc-modal-overlay {
          position: fixed; inset: 0;
          background: rgba(0,0,0,0.75);
          backdrop-filter: blur(8px);
          display: flex; align-items: center; justify-content: center;
          z-index: 2000; padding: 1.5rem;
        }
        .doc-modal {
          background: linear-gradient(135deg, #1e1b4b 0%, #0f172a 100%);
          border: 1px solid rgba(99,102,241,0.3);
          border-radius: 1.25rem;
          width: 100%; max-width: 900px; max-height: 85vh;
          display: flex; flex-direction: column;
          box-shadow: 0 25px 60px rgba(0,0,0,0.6);
        }
        .doc-modal-header {
          display: flex; justify-content: space-between; align-items: flex-start;
          padding: 1.5rem 1.5rem 1rem;
          border-bottom: 1px solid rgba(255,255,255,0.08);
        }
        .doc-modal-tabs {
          display: flex; gap: 0.5rem; padding: 1rem 1.5rem 0;
        }
        .tab-btn {
          background: transparent; border: 1px solid rgba(255,255,255,0.1);
          color: #94a3b8; padding: 0.5rem 1rem; border-radius: 0.5rem;
          cursor: pointer; font-size: 0.875rem; transition: all 0.2s;
        }
        .tab-btn:hover { background: rgba(255,255,255,0.05); }
        .tab-active { background: rgba(99,102,241,0.2) !important; border-color: #6366f1 !important; color: #a5b4fc !important; }
        .doc-modal-body {
          flex: 1; overflow: hidden; padding: 1rem 1.5rem;
          display: flex; flex-direction: column;
        }
        .content-pane {
          flex: 1; overflow-y: auto; background: rgba(0,0,0,0.3);
          border-radius: 0.75rem; border: 1px solid rgba(255,255,255,0.06);
          padding: 1rem;
        }
        .content-text {
          font-family: 'JetBrains Mono', 'Fira Code', monospace;
          font-size: 0.8rem; line-height: 1.8;
          color: #e2e8f0; white-space: pre-wrap; word-break: break-word;
          margin: 0;
        }
        .fixed-text { color: #86efac; }
        .loading-state {
          display: flex; flex-direction: column; align-items: center;
          justify-content: center; height: 200px; gap: 1rem; color: #94a3b8;
        }
        .spinner {
          width: 40px; height: 40px;
          border: 3px solid rgba(99,102,241,0.2);
          border-top-color: #6366f1;
          border-radius: 50%;
          animation: spin 0.8s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .doc-modal-footer {
          padding: 1rem 1.5rem;
          border-top: 1px solid rgba(255,255,255,0.08);
        }
        .violation-chips { display: flex; flex-wrap: wrap; gap: 0.4rem; }
        .violation-chip {
          background: rgba(239,68,68,0.15); border: 1px solid rgba(239,68,68,0.3);
          color: #fca5a5; padding: 0.25rem 0.6rem; border-radius: 2rem;
          font-size: 0.72rem;
        }
        .close-btn {
          background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.15);
          color: #94a3b8; width: 36px; height: 36px; border-radius: 50%;
          cursor: pointer; font-size: 1rem; display: flex; align-items: center; justify-content: center;
          transition: all 0.2s; flex-shrink: 0;
        }
        .close-btn:hover { background: rgba(239,68,68,0.2); color: #f87171; }
        .badge {
          padding: 0.2rem 0.7rem; border-radius: 2rem; font-size: 0.72rem; font-weight: 700;
        }
        .badge-pass { background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid rgba(16,185,129,0.3); }
        .badge-fail { background: rgba(239,68,68,0.15); color: #f87171; border: 1px solid rgba(239,68,68,0.3); }
        .badge-none { background: rgba(148,163,184,0.1); color: #94a3b8; border: 1px solid rgba(148,163,184,0.2); }
        .badge-score { background: rgba(99,102,241,0.15); color: #a5b4fc; border: 1px solid rgba(99,102,241,0.3); }
      `}</style>
        </div>
    );
}
