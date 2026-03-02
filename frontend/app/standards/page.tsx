"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import Link from "next/link";
import StandardApplicationModal from "@/components/StandardApplicationModal";

export default function StandardsPage() {
    const [standards, setStandards] = useState<any[]>([]);
    const [newStandardName, setNewStandardName] = useState("");
    const [newStandardDesc, setNewStandardDesc] = useState("");
    const [selectedStandard, setSelectedStandard] = useState<any>(null);
    const [expandedRules, setExpandedRules] = useState<string | null>(null);
    const [expandedVersions, setExpandedVersions] = useState<Record<string, any[]>>({});
    const [creating, setCreating] = useState(false);

    const loadStandards = async () => {
        try {
            const data = await api.getStandards();
            setStandards(data);
        } catch (e) { console.error(e); }
    };

    useEffect(() => { loadStandards(); }, []);

    const handleCreate = async () => {
        if (!newStandardName.trim()) return;
        setCreating(true);
        try {
            await api.createStandard(undefined, { name: newStandardName, description: newStandardDesc });
            setNewStandardName("");
            setNewStandardDesc("");
            loadStandards();
        } catch {
            alert("Failed to create standard");
        } finally { setCreating(false); }
    };

    const handleDeleteStandard = async (s: any) => {
        if (!confirm(`Are you sure you want to delete the standard "${s.name}"? This will also remove all its versions and historical validation records.`)) return;
        try {
            await api.deleteStandard(undefined, s.id);
            loadStandards();
        } catch (e: any) {
            alert(`Failed to delete standard: ${e.message}`);
        }
    };

    const loadVersions = async (standardId: string) => {
        if (expandedVersions[standardId]) {
            setExpandedVersions(prev => { const p = { ...prev }; delete p[standardId]; return p; });
            return;
        }
        try {
            const versions = await api.getStandardVersions(undefined, standardId);
            setExpandedVersions(prev => ({ ...prev, [standardId]: versions }));
        } catch { }
    };

    return (
        <main>
            <div className="app-header">
                <div>
                    <h1>Standards Management</h1>
                    <p style={{ color: "var(--text-secondary)", fontSize: "0.875rem", marginTop: "0.25rem" }}>
                        Create standards or promote documents as templates
                    </p>
                </div>
                <Link href="/" className="btn btn-outline">← Back to Dashboard</Link>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "340px 1fr", gap: "1.75rem" }}>
                {/* Create Standard */}
                <div>
                    <div className="glass-card">
                        <h3 style={{ marginBottom: "1rem" }}>➕ Create New Standard</h3>
                        <p style={{ color: "var(--text-secondary)", fontSize: "0.82rem", marginBottom: "1.25rem" }}>
                            Define a blank standard, then promote a document into it.
                        </p>
                        <div className="form-group">
                            <label>Standard Name</label>
                            <input
                                type="text"
                                placeholder="e.g. Corporate Policy Docs"
                                value={newStandardName}
                                onChange={e => setNewStandardName(e.target.value)}
                            />
                        </div>
                        <div className="form-group">
                            <label>Description</label>
                            <input
                                type="text"
                                placeholder="Brief description…"
                                value={newStandardDesc}
                                onChange={e => setNewStandardDesc(e.target.value)}
                            />
                        </div>
                        <button
                            onClick={handleCreate}
                            className="btn btn-primary"
                            style={{ width: "100%", marginTop: "0.5rem" }}
                            disabled={creating || !newStandardName.trim()}
                        >
                            {creating ? "Creating…" : "Create Standard"}
                        </button>
                        <div style={{ marginTop: "1.5rem", padding: "1rem", background: "rgba(99,102,241,0.07)", borderRadius: "0.75rem", border: "1px solid rgba(99,102,241,0.15)" }}>
                            <h4 style={{ fontSize: "0.8rem", color: "var(--primary-light)", marginBottom: "0.5rem" }}>💡 Workflow</h4>
                            <ol style={{ fontSize: "0.78rem", color: "var(--text-secondary)", paddingLeft: "1.25rem", lineHeight: 2 }}>
                                <li>Create a standard here</li>
                                <li>Go to Dashboard → select a reference file</li>
                                <li>Click <strong>⬆ Promote</strong> → AI extracts rules</li>
                                <li>Apply the standard to other documents</li>
                                <li>Use <strong>🔧 Auto-Fix</strong> to regenerate them</li>
                            </ol>
                        </div>
                    </div>
                </div>

                {/* Standards List */}
                <div>
                    <div className="glass-card">
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem" }}>
                            <h2>Active Standards</h2>
                            <span style={{ fontSize: "0.8rem", color: "var(--text-secondary)" }}>{standards.length} total</span>
                        </div>

                        {standards.length === 0 ? (
                            <div style={{ textAlign: "center", padding: "3rem 1rem", color: "var(--text-secondary)" }}>
                                <div style={{ fontSize: "2.5rem", marginBottom: "0.75rem" }}>📋</div>
                                <p>No standards yet. Create one above.</p>
                            </div>
                        ) : (
                            <div style={{ display: "flex", flexDirection: "column", gap: "0.875rem" }}>
                                {standards.map(s => (
                                    <div key={s.id} style={{ background: "rgba(255,255,255,0.02)", border: "1px solid var(--glass-border)", borderRadius: "0.875rem", padding: "1.25rem", transition: "border-color 0.2s" }}>
                                        {/* Standard header */}
                                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "0.75rem" }}>
                                            <div>
                                                <div style={{ fontWeight: 700, fontSize: "0.95rem" }}>{s.name}</div>
                                                {s.description && (
                                                    <div style={{ fontSize: "0.8rem", color: "var(--text-secondary)", marginTop: "0.25rem" }}>{s.description}</div>
                                                )}
                                                <div style={{ fontSize: "0.68rem", color: "var(--text-muted)", marginTop: "0.3rem", fontFamily: "monospace" }}>{s.id}</div>
                                            </div>
                                            <div style={{ display: "flex", gap: "0.4rem", flexShrink: 0 }}>
                                                <span className="status-badge badge-compliant">Active</span>
                                                <span style={{ fontSize: "0.75rem", color: "var(--text-secondary)", padding: "0.2rem 0.5rem", background: "rgba(255,255,255,0.05)", borderRadius: "0.35rem" }}>
                                                    {s.versions?.length || 0} version{s.versions?.length !== 1 ? "s" : ""}
                                                </span>
                                            </div>
                                        </div>

                                        {/* Actions */}
                                        <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
                                            <button className="btn btn-sm btn-primary" onClick={() => setSelectedStandard(s)}>
                                                📋 Apply Standard…
                                            </button>
                                            <button
                                                className="btn btn-sm btn-outline"
                                                onClick={() => loadVersions(s.id)}
                                            >
                                                {expandedVersions[s.id] ? "▲ Hide" : "▼ Versions"}
                                            </button>
                                            <button
                                                className="btn btn-sm btn-outline"
                                                style={{ border: "1px solid rgba(239, 68, 68, 0.4)", color: "#ef4444" }}
                                                onClick={() => handleDeleteStandard(s)}
                                            >
                                                🗑️ Delete
                                            </button>
                                        </div>

                                        {/* Versions list */}
                                        {expandedVersions[s.id] && (
                                            <div style={{ marginTop: "1rem", display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                                                {expandedVersions[s.id].length === 0 ? (
                                                    <p style={{ fontSize: "0.8rem", color: "var(--text-secondary)" }}>No versions yet. Promote a document to add one.</p>
                                                ) : expandedVersions[s.id].map((v: any) => (
                                                    <div key={v.id} style={{ background: "rgba(0,0,0,0.25)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: "0.625rem", padding: "0.875rem" }}>
                                                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
                                                            <span style={{ fontSize: "0.875rem", fontWeight: 600 }}>
                                                                v{v.version_number}
                                                                {v.is_active && <span style={{ marginLeft: "0.5rem", fontSize: "0.68rem", color: "#34d399" }}>● Active</span>}
                                                            </span>
                                                            <span style={{ fontSize: "0.72rem", color: "var(--text-secondary)" }}>
                                                                {new Date(v.created_at).toLocaleDateString()}
                                                            </span>
                                                        </div>
                                                        {v.rules_json && (
                                                            <div>
                                                                <button
                                                                    className="btn btn-sm btn-outline"
                                                                    style={{ fontSize: "0.7rem", marginBottom: "0.5rem" }}
                                                                    onClick={() => setExpandedRules(expandedRules === v.id ? null : v.id)}
                                                                >
                                                                    {expandedRules === v.id ? "▲ Hide Rules" : "⚙ View Extracted Rules"}
                                                                </button>
                                                                {expandedRules === v.id && (() => {
                                                                    const r = v.rules_json;
                                                                    const docType = r?.document_type;
                                                                    const authModel = r?.authority_model;
                                                                    const compModel = r?.compliance_model;
                                                                    const domains = r?.domain_markers || [];
                                                                    const lang = r?.rules?.language || {};
                                                                    const structure = r?.rules?.structure || {};
                                                                    const meta = r?.rules?.metadata || {};
                                                                    const vocabMap = lang.controlled_vocabulary_map || {};
                                                                    const vocabEntries = Object.entries(vocabMap).filter(([, v]) => v);
                                                                    const hasMeta = docType || authModel;

                                                                    const badgeStyle = (bg: string, color: string, border: string) => ({
                                                                        padding: "0.15rem 0.55rem", borderRadius: "2rem", fontSize: "0.68rem",
                                                                        fontWeight: 700 as const, background: bg, color, border: `1px solid ${border}`, marginRight: "0.3rem"
                                                                    });

                                                                    return (
                                                                        <div style={{ background: "rgba(0,0,0,0.35)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: "0.5rem", padding: "1rem", fontSize: "0.78rem", lineHeight: 1.7 }}>
                                                                            {/* Type & Model badges */}
                                                                            {hasMeta && (
                                                                                <div style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap", marginBottom: "0.75rem" }}>
                                                                                    {docType && <span style={badgeStyle("rgba(99,102,241,0.15)", "#a5b4fc", "rgba(99,102,241,0.3)")}>📄 {docType}</span>}
                                                                                    {authModel && <span style={badgeStyle("rgba(245,158,11,0.12)", "#fbbf24", "rgba(245,158,11,0.3)")}>🔑 {authModel.replace("_", " ")}</span>}
                                                                                    {compModel && compModel !== "none" && <span style={badgeStyle("rgba(16,185,129,0.12)", "#34d399", "rgba(16,185,129,0.3)")}>✅ {compModel.replace("_", " ")}</span>}
                                                                                    {lang.tone && <span style={badgeStyle("rgba(139,92,246,0.12)", "#c4b5fd", "rgba(139,92,246,0.3)")}>🎯 {lang.tone}</span>}
                                                                                </div>
                                                                            )}

                                                                            {/* Hierarchy Pattern */}
                                                                            {structure.hierarchy_pattern && (
                                                                                <div style={{ marginBottom: "0.6rem", padding: "0.4rem 0.7rem", background: "rgba(99,102,241,0.06)", borderRadius: "0.4rem", border: "1px solid rgba(99,102,241,0.12)" }}>
                                                                                    <span style={{ fontSize: "0.66rem", color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.06em" }}>Hierarchy: </span>
                                                                                    <span style={{ color: "#c4b5fd", fontFamily: "monospace", fontSize: "0.74rem" }}>{structure.hierarchy_pattern}</span>
                                                                                </div>
                                                                            )}

                                                                            {/* Mandatory Sections */}
                                                                            {structure.mandatory_sections?.length > 0 && (
                                                                                <div style={{ marginBottom: "0.6rem" }}>
                                                                                    <div style={{ fontSize: "0.66rem", color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: "0.3rem" }}>Mandatory Sections</div>
                                                                                    <div style={{ display: "flex", gap: "0.25rem", flexWrap: "wrap" }}>
                                                                                        {structure.mandatory_sections.map((s: string, i: number) => (
                                                                                            <span key={i} style={{ padding: "0.12rem 0.45rem", borderRadius: "0.25rem", fontSize: "0.7rem", background: "rgba(255,255,255,0.05)", color: "#cbd5e1", border: "1px solid rgba(255,255,255,0.08)" }}>{s}</span>
                                                                                        ))}
                                                                                    </div>
                                                                                </div>
                                                                            )}

                                                                            {/* Controlled Vocabulary Table */}
                                                                            {vocabEntries.length > 0 && (
                                                                                <div style={{ marginBottom: "0.6rem" }}>
                                                                                    <div style={{ fontSize: "0.66rem", color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: "0.3rem" }}>Controlled Vocabulary</div>
                                                                                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.74rem" }}>
                                                                                        <thead>
                                                                                            <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
                                                                                                <th style={{ textAlign: "left", padding: "0.25rem 0.5rem", color: "#64748b", fontWeight: 600 }}>Term</th>
                                                                                                <th style={{ textAlign: "left", padding: "0.25rem 0.5rem", color: "#64748b", fontWeight: 600 }}>Meaning</th>
                                                                                            </tr>
                                                                                        </thead>
                                                                                        <tbody>
                                                                                            {vocabEntries.map(([term, meaning], i) => (
                                                                                                <tr key={i} style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
                                                                                                    <td style={{ padding: "0.2rem 0.5rem", fontWeight: 700, color: "#e2e8f0", fontFamily: "monospace" }}>{term}</td>
                                                                                                    <td style={{ padding: "0.2rem 0.5rem", color: "#94a3b8" }}>{String(meaning)}</td>
                                                                                                </tr>
                                                                                            ))}
                                                                                        </tbody>
                                                                                    </table>
                                                                                </div>
                                                                            )}

                                                                            {/* Domain Markers */}
                                                                            {domains.length > 0 && (
                                                                                <div style={{ marginBottom: "0.6rem" }}>
                                                                                    <div style={{ fontSize: "0.66rem", color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: "0.3rem" }}>Domain Markers</div>
                                                                                    <div style={{ display: "flex", gap: "0.25rem", flexWrap: "wrap" }}>
                                                                                        {domains.map((d: string, i: number) => (
                                                                                            <span key={i} style={{ padding: "0.12rem 0.5rem", borderRadius: "2rem", fontSize: "0.68rem", fontWeight: 600, background: "rgba(16,185,129,0.1)", color: "#34d399", border: "1px solid rgba(16,185,129,0.25)" }}>{d}</span>
                                                                                        ))}
                                                                                    </div>
                                                                                </div>
                                                                            )}

                                                                            {/* Traceability */}
                                                                            {meta.traceability && (
                                                                                <div style={{ marginBottom: "0.6rem" }}>
                                                                                    <div style={{ fontSize: "0.66rem", color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: "0.3rem" }}>Traceability</div>
                                                                                    <div style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap" }}>
                                                                                        {meta.traceability.part_numbers && <span style={badgeStyle("rgba(139,92,246,0.1)", "#c4b5fd", "rgba(139,92,246,0.2)")}>Part Numbers</span>}
                                                                                        {meta.traceability.figure_references && <span style={badgeStyle("rgba(139,92,246,0.1)", "#c4b5fd", "rgba(139,92,246,0.2)")}>Figure Refs</span>}
                                                                                        {meta.traceability.form_numbers && <span style={badgeStyle("rgba(139,92,246,0.1)", "#c4b5fd", "rgba(139,92,246,0.2)")}>Form Numbers</span>}
                                                                                        {meta.traceability.annex_references && <span style={badgeStyle("rgba(139,92,246,0.1)", "#c4b5fd", "rgba(139,92,246,0.2)")}>Annex Refs</span>}
                                                                                    </div>
                                                                                </div>
                                                                            )}

                                                                            {/* Raw JSON fallback */}
                                                                            <details style={{ marginTop: "0.5rem" }}>
                                                                                <summary style={{ fontSize: "0.66rem", color: "#475569", cursor: "pointer" }}>Raw JSON</summary>
                                                                                <pre style={{ fontSize: "0.68rem", color: "#86efac", lineHeight: 1.6, overflowX: "auto", maxHeight: "200px", whiteSpace: "pre-wrap", wordBreak: "break-word", marginTop: "0.4rem" }}>
                                                                                    {JSON.stringify(r, null, 2)}
                                                                                </pre>
                                                                            </details>
                                                                        </div>
                                                                    );
                                                                })()}
                                                            </div>
                                                        )}
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            </div>

            {selectedStandard && (
                <StandardApplicationModal
                    standard={selectedStandard}
                    onClose={() => setSelectedStandard(null)}
                    onSuccess={() => console.log("Applied")}
                />
            )}
        </main>
    );
}
