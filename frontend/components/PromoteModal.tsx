"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";

interface PromoteModalProps {
    document: any;
    onClose: () => void;
    onSuccess: () => void;
}

export default function PromoteModal({ document, onClose, onSuccess }: PromoteModalProps) {
    const [standards, setStandards] = useState<any[]>([]);
    const [selectedStandardId, setSelectedStandardId] = useState("");
    const [newStandardName, setNewStandardName] = useState("");
    const [newStandardDesc, setNewStandardDesc] = useState("");
    const [mode, setMode] = useState<"existing" | "create">("existing");
    const [loading, setLoading] = useState(false);
    const [done, setDone] = useState(false);
    const [extractedRules, setExtractedRules] = useState<any>(null);

    useEffect(() => {
        api.getStandards().then(setStandards).catch(console.error);
    }, []);

    const handlePromote = async () => {
        setLoading(true);
        try {
            let standardId = selectedStandardId;

            // Create new standard if needed
            if (mode === "create") {
                if (!newStandardName) { alert("Enter a standard name"); setLoading(false); return; }
                const created = await api.createStandard(undefined, { name: newStandardName, description: newStandardDesc });
                standardId = created.id;
            }

            if (!standardId) { alert("Select a standard"); setLoading(false); return; }

            // Promote document to standard (AI extracts rules)
            const version = await api.promoteToStandard(undefined, standardId, document.id);
            setExtractedRules(version.rules_json);
            setDone(true);
            onSuccess();
        } catch (e: any) {
            alert(`Promotion failed: ${e.message}`);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="modal-overlay" onClick={onClose}>
            <div className="promote-modal" onClick={e => e.stopPropagation()}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem" }}>
                    <h3 style={{ fontSize: "1.1rem", fontWeight: 700 }}>⬆ Promote to Standard</h3>
                    <button className="close-btn" onClick={onClose}>✕</button>
                </div>

                <p style={{ color: "#94a3b8", fontSize: "0.87rem", marginBottom: "1.5rem" }}>
                    AI will extract structural rules from <strong style={{ color: "#e2e8f0" }}>{document.filename}</strong> and create a reusable standard.
                </p>

                {!done ? (
                    <>
                        {/* Mode selector */}
                        <div className="mode-toggle">
                            <button
                                className={`mode-btn ${mode === "existing" ? "mode-active" : ""}`}
                                onClick={() => setMode("existing")}
                            >Use Existing Standard</button>
                            <button
                                className={`mode-btn ${mode === "create" ? "mode-active" : ""}`}
                                onClick={() => setMode("create")}
                            >Create New Standard</button>
                        </div>

                        {mode === "existing" ? (
                            <div style={{ marginTop: "1rem" }}>
                                <label className="field-label">Select Standard</label>
                                <select
                                    value={selectedStandardId}
                                    onChange={e => setSelectedStandardId(e.target.value)}
                                    className="field-select"
                                >
                                    <option value="">-- Choose a standard --</option>
                                    {standards.map(s => (
                                        <option key={s.id} value={s.id}>{s.name}</option>
                                    ))}
                                </select>
                                {standards.length === 0 && (
                                    <p style={{ fontSize: "0.8rem", color: "#f59e0b", marginTop: "0.5rem" }}>
                                        No standards yet. Switch to "Create New Standard".
                                    </p>
                                )}
                            </div>
                        ) : (
                            <div style={{ marginTop: "1rem" }}>
                                <div style={{ marginBottom: "0.75rem" }}>
                                    <label className="field-label">Standard Name</label>
                                    <input
                                        className="field-input"
                                        placeholder="e.g. Corporate Policy Docs"
                                        value={newStandardName}
                                        onChange={e => setNewStandardName(e.target.value)}
                                    />
                                </div>
                                <div>
                                    <label className="field-label">Description (optional)</label>
                                    <input
                                        className="field-input"
                                        placeholder="Briefly describe this standard"
                                        value={newStandardDesc}
                                        onChange={e => setNewStandardDesc(e.target.value)}
                                    />
                                </div>
                            </div>
                        )}

                        <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end", marginTop: "2rem" }}>
                            <button className="btn-cancel" onClick={onClose} disabled={loading}>Cancel</button>
                            <button className="btn-promote" onClick={handlePromote} disabled={loading}>
                                {loading ? (
                                    <><span className="spin">⟳</span> AI Extracting Rules...</>
                                ) : "Extract & Promote"}
                            </button>
                        </div>
                    </>
                ) : (
                    <div className="success-view">
                        <div className="success-icon">✓</div>
                        <h4 style={{ color: "#34d399", marginBottom: "0.5rem" }}>Promotion Successful!</h4>
                        <p style={{ color: "#94a3b8", fontSize: "0.87rem", marginBottom: "1.5rem" }}>
                            AI extracted the following rules from your document:
                        </p>
                        {extractedRules && (
                            <pre className="rules-preview">{JSON.stringify(extractedRules, null, 2)}</pre>
                        )}
                        <button className="btn-promote" style={{ marginTop: "1.5rem", width: "100%" }} onClick={onClose}>
                            Done
                        </button>
                    </div>
                )}
            </div>

            <style>{`
        .modal-overlay {
          position: fixed; inset: 0; background: rgba(0,0,0,0.7);
          backdrop-filter: blur(8px); display: flex; align-items: center;
          justify-content: center; z-index: 2000; padding: 1rem;
        }
        .promote-modal {
          background: linear-gradient(135deg, #1e1b4b 0%, #0f172a 100%);
          border: 1px solid rgba(99,102,241,0.3); border-radius: 1.25rem;
          padding: 2rem; width: 100%; max-width: 500px;
          box-shadow: 0 25px 60px rgba(0,0,0,0.6); max-height: 90vh; overflow-y: auto;
        }
        .mode-toggle {
          display: flex; gap: 0.5rem; background: rgba(0,0,0,0.3);
          padding: 0.25rem; border-radius: 0.5rem;
        }
        .mode-btn {
          flex: 1; padding: 0.5rem 0.75rem; border: none; border-radius: 0.35rem;
          cursor: pointer; font-size: 0.8rem; background: transparent; color: #94a3b8;
          transition: all 0.2s;
        }
        .mode-active { background: rgba(99,102,241,0.25) !important; color: #a5b4fc !important; }
        .field-label { display: block; margin-bottom: 0.4rem; font-size: 0.8rem; color: #94a3b8; }
        .field-input, .field-select {
          width: 100%; background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.1);
          border-radius: 0.5rem; padding: 0.6rem 0.8rem; color: #f8fafc; font-size: 0.875rem;
          outline: none;
        }
        .field-input:focus, .field-select:focus { border-color: rgba(99,102,241,0.5); }
        .field-select option { background: #1e1b4b; }
        .btn-cancel {
          background: transparent; border: 1px solid rgba(255,255,255,0.15); color: #94a3b8;
          padding: 0.6rem 1.2rem; border-radius: 0.5rem; cursor: pointer; font-size: 0.875rem;
        }
        .btn-promote {
          background: linear-gradient(135deg, #6366f1, #8b5cf6); border: none; color: white;
          padding: 0.6rem 1.4rem; border-radius: 0.5rem; cursor: pointer; font-size: 0.875rem;
          font-weight: 600; display: flex; align-items: center; gap: 0.5rem;
          transition: all 0.2s; box-shadow: 0 4px 15px rgba(99,102,241,0.3);
        }
        .btn-promote:hover { box-shadow: 0 6px 20px rgba(99,102,241,0.5); transform: translateY(-1px); }
        .btn-promote:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
        .spin { display: inline-block; animation: spin 0.6s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }
        .close-btn {
          background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.15);
          color: #94a3b8; width: 32px; height: 32px; border-radius: 50%; cursor: pointer;
          font-size: 0.9rem; display: flex; align-items: center; justify-content: center;
        }
        .success-view { text-align: center; }
        .success-icon {
          width: 60px; height: 60px; border-radius: 50%;
          background: rgba(16,185,129,0.2); border: 2px solid #10b981;
          color: #34d399; font-size: 1.75rem; display: flex; align-items: center;
          justify-content: center; margin: 0 auto 1rem;
        }
        .rules-preview {
          background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.06);
          border-radius: 0.75rem; padding: 1rem; font-size: 0.72rem;
          color: #86efac; line-height: 1.6; overflow-y: auto; max-height: 300px;
          text-align: left; white-space: pre-wrap; word-break: break-word;
        }
      `}</style>
        </div>
    );
}
