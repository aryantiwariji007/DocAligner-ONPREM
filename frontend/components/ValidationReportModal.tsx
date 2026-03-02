"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface ValidationReportModalProps {
    report: any;
    filename: string;
    documentId?: string;
    onClose: () => void;
}

// ── Simple LCS-based diff ───────────────────────────────────────────────────
type DiffLine = { type: "equal" | "added" | "removed"; text: string; lineNo?: number };

function computeDiff(original: string, fixed: string): DiffLine[] {
    // Normalize line endings and whitespace for more robust comparison
    const rawA = original.replace(/\r\n/g, "\n");
    const rawB = fixed.replace(/\r\n/g, "\n");

    const aLines = rawA.split("\n");
    const bLines = rawB.split("\n");
    const m = aLines.length, n = bLines.length;

    // Helper to compare lines ignoring subtle whitespace
    const areLinesEqual = (l1: string, l2: string) => l1.trim() === l2.trim();

    // Build LCS table
    const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
    for (let i = 1; i <= m; i++)
        for (let j = 1; j <= n; j++)
            dp[i][j] = areLinesEqual(aLines[i - 1], bLines[j - 1])
                ? dp[i - 1][j - 1] + 1
                : Math.max(dp[i - 1][j], dp[i][j - 1]);

    // Backtrack
    const result: DiffLine[] = [];
    let i = m, j = n;
    while (i > 0 || j > 0) {
        if (i > 0 && j > 0 && areLinesEqual(aLines[i - 1], bLines[j - 1])) {
            result.unshift({ type: "equal", text: bLines[j - 1], lineNo: j });
            i--; j--;
        } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
            result.unshift({ type: "added", text: bLines[j - 1], lineNo: j });
            j--;
        } else {
            result.unshift({ type: "removed", text: aLines[i - 1] });
            i--;
        }
    }
    return result;
}


// ── Severity badge ──────────────────────────────────────────────────────────
function SeverityBadge({ severity }: { severity: string }) {
    const map: Record<string, { bg: string; color: string; border: string }> = {
        high: { bg: "rgba(239,68,68,0.15)", color: "#f87171", border: "rgba(239,68,68,0.35)" },
        medium: { bg: "rgba(245,158,11,0.15)", color: "#fbbf24", border: "rgba(245,158,11,0.35)" },
        low: { bg: "rgba(99,102,241,0.12)", color: "#a5b4fc", border: "rgba(99,102,241,0.3)" },
    };
    const s = (severity || "low").toLowerCase();
    const style = map[s] || map.low;
    return (
        <span style={{
            padding: "0.1rem 0.55rem", borderRadius: "2rem", fontSize: "0.65rem", fontWeight: 700,
            letterSpacing: "0.06em", textTransform: "uppercase", background: style.bg, color: style.color,
            border: `1px solid ${style.border}`, flexShrink: 0
        }}>
            {severity || "low"}
        </span>
    );
}

// ── Main Component ──────────────────────────────────────────────────────────
export default function ValidationReportModal({ report, filename, documentId, onClose }: ValidationReportModalProps) {
    const [localReport, setLocalReport] = useState(report);
    const [activeTab, setActiveTab] = useState<"violations" | "decision" | "preview" | "diff" | "deviations">("violations");
    const [fixLoading, setFixLoading] = useState(false);
    const [fixResult, setFixResult] = useState<{ fixed_content: string; original_content: string; fixed_pdf_path?: string } | null>(
        localReport?.report?.fixed_content
            ? {
                fixed_content: localReport.report.fixed_content,
                original_content: localReport.report.decision_flow?.original_content || "",
                fixed_pdf_path: localReport.report.fixed_pdf_path
            }
            : null
    );
    const [copied, setCopied] = useState(false);
    const [decisionFlow, setDecisionFlow] = useState<any>(localReport?.report?.decision_flow || null);
    const [competenceLevel, setCompetenceLevel] = useState<string>("general");
    const [isFullscreen, setIsFullscreen] = useState(false);

    useEffect(() => {
        let interval: NodeJS.Timeout;
        if (localReport?.status === "PENDING") {
            interval = setInterval(async () => {
                try {
                    const docIdToFetch = documentId || localReport.document_id;
                    if (!docIdToFetch) return;
                    const latest = await api.getDocumentValidation(undefined, docIdToFetch);
                    if (latest) {
                        setLocalReport(latest);

                        // If we just finished a fix, update the decision flow and fix result
                        if (latest.status !== "PENDING" && latest.report?.fixed_content) {
                            setDecisionFlow(latest.report.decision_flow || null);
                            setFixResult({
                                fixed_content: latest.report.fixed_content,
                                original_content: latest.report.decision_flow?.original_content || "",
                                fixed_pdf_path: latest.report.fixed_pdf_path
                            });
                            setActiveTab("preview");
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
    }, [localReport?.status, documentId]);

    if (!localReport) return null;

    if (localReport.status === "PENDING") {
        return (
            <div className="modal-overlay">
                <div className="report-modal glass-card" style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "350px", textAlign: "center" }}>
                    <div style={{
                        width: "50px", height: "50px", borderRadius: "50%",
                        border: "4px solid rgba(139,92,246,0.1)", borderTop: "4px solid #8b5cf6",
                        animation: "spin 1s linear infinite", marginBottom: "1.5rem"
                    }} />
                    <h3 style={{ fontSize: "1.2rem", fontWeight: 700, marginBottom: "0.5rem" }}>Evaluating Compliance...</h3>
                    <p style={{ color: "#94a3b8", fontSize: "0.9rem", maxWidth: "80%", lineHeight: 1.5 }}>
                        The AI is currently analyzing <strong style={{ color: "#c4b5fd" }}>{filename}</strong> against the standard.<br />
                        This process involves deep semantic evaluation and may take a moment.
                    </p>
                    {localReport.report_json?.message && (
                        <div style={{ marginTop: "1rem", fontSize: "0.8rem", color: "#64748b", fontStyle: "italic" }}>
                            Status: {localReport.report_json.message}
                        </div>
                    )}
                    <button onClick={onClose} style={{
                        marginTop: "2rem", padding: "0.5rem 1.5rem", background: "rgba(255,255,255,0.05)",
                        border: "1px solid rgba(255,255,255,0.1)", borderRadius: "0.4rem", color: "#94a3b8", cursor: "pointer"
                    }}>
                        Close Background Task
                    </button>
                    <style dangerouslySetInnerHTML={{ __html: `@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }` }} />
                </div>
            </div>
        );
    }

    const inner = localReport.report || localReport;
    const scorecard: any = inner.ai_evaluation?.scorecard || null;
    const { score, compliant, errors = [], warnings = [] } = inner;
    // Use scorecard.overall as the display score if available (more reliable than top-level score)
    const displayScore = scorecard?.overall ?? score;
    // Trust AI evaluation compliance over deterministic result, AND enforce 75% rule
    const aiCompliant = inner.ai_evaluation?.compliant;
    const isCompliant = (displayScore >= 75) ? true : (aiCompliant !== undefined ? aiCompliant : (report.status === "COMPLIANT" || compliant));
    const aiViolations: any[] = inner.ai_evaluation?.violations || [];
    const compatibilityScore: number | undefined = inner.ai_evaluation?.compatibility_score;
    const compatibilityWarning: string | undefined = inner.ai_evaluation?.compatibility_warning;
    const skippedRules: any[] = inner.ai_evaluation?.skipped_rules || [];
    const obligationSummary: any[] = inner.ai_evaluation?.obligation_summary || [];
    const [showSkipped, setShowSkipped] = useState(false);
    const [showPreserved, setShowPreserved] = useState(false);

    const highCount = aiViolations.filter(v => (v.severity || "").toLowerCase() === "high").length;
    const mediumCount = aiViolations.filter(v => (v.severity || "").toLowerCase() === "medium").length;
    const lowCount = aiViolations.filter(v => (v.severity || "").toLowerCase() === "low").length;
    const deterministicErrors = errors.filter((e: string) => !e.startsWith("[MANDATORY]") && !e.startsWith("[RECOMMENDED]") && !e.startsWith("[AI]"));

    const handleFix = async () => {
        const docId = documentId || report.document_id;
        if (!docId) { alert("Cannot auto-fix: no document ID available."); return; }
        setFixLoading(true);
        try {
            // Pre-fetch original content so diff is always populated
            let originalText = "";
            try {
                const contentResp = await api.getDocumentContent(undefined, docId);
                originalText = contentResp?.content || "";
            } catch { /* ignore */ }

            const result = await api.fixDocument(undefined, docId, competenceLevel);

            if (result.status === "async_triggered") {
                // Trigger the polling logic by setting status to PENDING
                setLocalReport({ ...localReport, status: "PENDING" });
                setFixLoading(false);
                return;
            }

            if (result.decision_flow) {
                setDecisionFlow(result.decision_flow);
            }
            // Use original from API response, fall back to pre-fetched text
            const origContent = result.original_content || originalText;
            if (result.fixed_content) {
                setFixResult({
                    fixed_content: result.fixed_content,
                    original_content: origContent,
                    fixed_pdf_path: result.fixed_pdf_path
                });
            }
            setActiveTab(result.decision_flow ? "decision" : "preview");
        } catch (e: any) {
            alert(`Auto-fix failed: ${e.response?.data?.detail || e.message || "Unknown error"}`);
        } finally {
            setFixLoading(false);
        }
    };

    const handleCopy = () => {
        if (!fixResult?.fixed_content) return;
        navigator.clipboard.writeText(fixResult.fixed_content);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    };

    const handleDownloadPDF = () => {
        const docId = documentId || report.document_id;
        if (!docId) return;

        // Check if we have a specific PDF path from the fixResult or report
        const pdfPath = fixResult?.fixed_pdf_path || inner.fixed_pdf_path;
        const downloadUrl = api.getDocumentDownloadUrl(docId, pdfPath);

        // Trigger download
        const link = document.createElement("a");
        link.href = downloadUrl;
        link.setAttribute("download", `${filename.replace(/\.[^/.]+$/, "")}_fixed.pdf`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    };

    // Compute diff lazily only when diff tab is active
    const diffLines: DiffLine[] = activeTab === "diff" && fixResult
        ? computeDiff(fixResult.original_content || "", fixResult.fixed_content || "")
        : [];

    const addedCount = diffLines.filter(d => d.type === "added").length;
    const removedCount = diffLines.filter(d => d.type === "removed").length;

    // Helper renderers
    const renderExpertEvaluation = (data: any) => {
        if (!data) return null;
        return (
            <div style={{ marginBottom: "1.1rem", background: "rgba(255,255,255,0.02)", padding: "0.75rem", borderRadius: "0.6rem", border: "1px solid rgba(255,255,255,0.08)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "0.6rem" }}>
                    <h4 style={{ fontSize: "0.7rem", textTransform: "uppercase", letterSpacing: "0.08em", color: "#c084fc", margin: 0 }}>
                        🏗️ Structural Scorer (Pure Python)
                    </h4>
                    {data.confidence && (
                        <span style={{
                            fontSize: "0.65rem", fontWeight: 700, padding: "0.15rem 0.5rem", borderRadius: "1rem", textTransform: "uppercase",
                            background: data.confidence === 'high' ? "rgba(16,185,129,0.15)" : data.confidence === 'medium' ? "rgba(245,158,11,0.15)" : "rgba(239,68,68,0.15)",
                            color: data.confidence === 'high' ? "#34d399" : data.confidence === 'medium' ? "#fbbf24" : "#f87171"
                        }}>
                            Confidence: {data.confidence}
                        </span>
                    )}
                </div>

                {data.reviewer_notes && (
                    <div style={{ marginBottom: "0.75rem", fontSize: "0.8rem", color: "#cbd5e1", lineHeight: 1.5, fontStyle: "italic", borderLeft: "2px solid #8b5cf6", paddingLeft: "0.5rem" }}>
                        "{data.reviewer_notes}"
                    </div>
                )}

                {data.risk_areas && data.risk_areas.length > 0 && (
                    <div>
                        <div style={{ fontSize: "0.68rem", color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "0.3rem", fontWeight: 700 }}>
                            ⚠ Identified Risk Areas
                        </div>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}>
                            {data.risk_areas.map((area: string, i: number) => (
                                <span key={i} style={{ padding: "0.2rem 0.5rem", borderRadius: "0.4rem", fontSize: "0.72rem", background: "rgba(239,68,68,0.1)", color: "#fca5a5", border: "1px solid rgba(239,68,68,0.2)" }}>
                                    {area}
                                </span>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        );
    };

    // Tabs available
    // Extract deviations from decisionFlow
    const deviations: any[] = decisionFlow?.deviations || [];
    const preservedItems: string[] = decisionFlow?.preserved_items || [];
    const changeSummary: string = decisionFlow?.change_summary || "";

    const tabs: { id: string; label: string }[] = [
        { id: "violations", label: "Violations" },
        ...(decisionFlow ? [{ id: "decision", label: "🔒 Decision Flow" }] : []),
        ...(deviations.length > 0 ? [{ id: "deviations", label: `📋 Deviations (${deviations.length})` }] : []),
        ...(fixResult ? [
            { id: "preview", label: "✨ Fixed Preview" },
            { id: "diff", label: `Diff  (+${addedCount} / -${removedCount})` },
        ] : []),
    ];

    return (
        <div className="modal-overlay">
            <div className="report-modal glass-card">

                {/* ── Header ── */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1rem" }}>
                    <div>
                        <h3 style={{ fontSize: "1rem", fontWeight: 700 }}>Compliance Report</h3>
                        <div style={{ fontSize: "0.78rem", color: "#94a3b8", marginTop: "0.15rem" }}>{filename}</div>
                    </div>
                    <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
                        {compatibilityScore !== undefined && displayScore < 75 && (
                            <div style={{
                                padding: "0.25rem 0.6rem", borderRadius: "0.5rem", fontSize: "0.68rem", fontWeight: 600,
                                background: compatibilityScore >= 70 ? "rgba(16,185,129,0.1)" : compatibilityScore >= 40 ? "rgba(245,158,11,0.1)" : "rgba(239,68,68,0.1)",
                                color: compatibilityScore >= 70 ? "#34d399" : compatibilityScore >= 40 ? "#fbbf24" : "#f87171",
                                border: `1px solid ${compatibilityScore >= 70 ? "rgba(16,185,129,0.3)" : compatibilityScore >= 40 ? "rgba(245,158,11,0.3)" : "rgba(239,68,68,0.3)"}`
                            }}>
                                🎯 Domain Match: {Math.round(compatibilityScore)}%
                            </div>
                        )}
                        <div className={`score-badge-lg ${isCompliant ? "score-pass" : "score-fail"}`}>
                            {displayScore !== undefined ? `${Math.round(displayScore)}%` : (isCompliant ? "PASS" : "FAIL")}
                        </div>
                        <button className="close-x" onClick={onClose}>✕</button>
                    </div>
                </div>

                {/* ── Score bar ── */}
                {displayScore !== undefined && (
                    <div style={{ marginBottom: "1.1rem" }}>
                        <div style={{ height: "5px", background: "rgba(255,255,255,0.07)", borderRadius: "3px", overflow: "hidden" }}>
                            <div style={{
                                height: "100%", width: `${displayScore}%`, borderRadius: "3px",
                                background: displayScore >= 70 ? "linear-gradient(90deg,#10b981,#34d399)"
                                    : displayScore >= 40 ? "linear-gradient(90deg,#f59e0b,#fbbf24)"
                                        : "linear-gradient(90deg,#ef4444,#f87171)", transition: "width 0.5s ease"
                            }} />
                        </div>
                        <div style={{ display: "flex", justifyContent: "space-between", marginTop: "0.35rem", fontSize: "0.68rem", color: "#64748b" }}>
                            <span>Compliance Score</span>
                            <span>{isCompliant ? "✓ Passes All Checks" : "✗ Improvements Needed"}</span>
                        </div>
                    </div>
                )}

                {/* ── Status pill ── */}
                <div style={{
                    padding: "0.65rem 1rem", borderRadius: "0.5rem", marginBottom: "1.1rem",
                    background: isCompliant ? "rgba(16,185,129,0.08)" : "rgba(239,68,68,0.08)",
                    border: `1px solid ${isCompliant ? "rgba(16,185,129,0.2)" : "rgba(239,68,68,0.2)"}`
                }}>
                    <span style={{ color: isCompliant ? "#34d399" : "#f87171", fontWeight: 600, fontSize: "0.88rem" }}>
                        {isCompliant ? "✓ Compliant with Standards" : "✗ Non-Compliant – Violations Found"}
                    </span>
                </div>

                {/* ── Compatibility Warning ── */}
                {compatibilityWarning && displayScore < 75 && (
                    <div style={{
                        padding: "0.6rem 1rem", borderRadius: "0.5rem", marginBottom: "0.75rem",
                        background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.2)",
                        display: "flex", alignItems: "flex-start", gap: "0.5rem"
                    }}>
                        <span style={{ fontSize: "1rem", flexShrink: 0 }}>⚠️</span>
                        <span style={{ fontSize: "0.8rem", color: "#fde68a", lineHeight: 1.5 }}>
                            <strong style={{ color: "#fbbf24" }}>Low Domain Compatibility: </strong>
                            {compatibilityWarning}
                        </span>
                    </div>
                )}

                {/* ── Tab bar ── */}
                <div style={{ display: "flex", gap: "0.25rem", marginBottom: "1rem", borderBottom: "1px solid rgba(255,255,255,0.08)", paddingBottom: "0.5rem" }}>
                    {tabs.map(tab => (
                        <button key={tab.id} onClick={() => setActiveTab(tab.id as any)}
                            style={{
                                padding: "0.35rem 0.85rem", borderRadius: "0.4rem", fontSize: "0.78rem",
                                fontWeight: activeTab === tab.id ? 700 : 500, cursor: "pointer", border: "none",
                                background: activeTab === tab.id ? "rgba(139,92,246,0.2)" : "transparent",
                                color: activeTab === tab.id ? "#c4b5fd" : "#64748b",
                                borderBottom: activeTab === tab.id ? "2px solid #8b5cf6" : "2px solid transparent"
                            }}>
                            {tab.label}
                        </button>
                    ))}
                </div>

                {/* ═══════════════ TAB: VIOLATIONS ═══════════════ */}
                {activeTab === "violations" && (
                    <div style={{ maxHeight: "340px", overflowY: "auto" }}>

                        {/* ── Expert Evaluation (Initial Snapshot) ── */}
                        {renderExpertEvaluation(inner.ai_evaluation)}

                        {/* Severity summary */}
                        {aiViolations.length > 0 && (
                            <div style={{ display: "flex", gap: "0.45rem", marginBottom: "1rem", flexWrap: "wrap" }}>
                                {highCount > 0 && <div style={{ padding: "0.25rem 0.7rem", borderRadius: "2rem", fontSize: "0.73rem", fontWeight: 700, background: "rgba(239,68,68,0.12)", color: "#f87171", border: "1px solid rgba(239,68,68,0.3)" }}>🔴 {highCount} High</div>}
                                {mediumCount > 0 && <div style={{ padding: "0.25rem 0.7rem", borderRadius: "2rem", fontSize: "0.73rem", fontWeight: 700, background: "rgba(245,158,11,0.12)", color: "#fbbf24", border: "1px solid rgba(245,158,11,0.3)" }}>🟡 {mediumCount} Medium</div>}
                                {lowCount > 0 && <div style={{ padding: "0.25rem 0.7rem", borderRadius: "2rem", fontSize: "0.73rem", fontWeight: 700, background: "rgba(99,102,241,0.1)", color: "#a5b4fc", border: "1px solid rgba(99,102,241,0.25)" }}>🔵 {lowCount} Low</div>}
                            </div>
                        )}

                        {/* AI Violations */}
                        {aiViolations.length > 0 && (
                            <div style={{ marginBottom: "1rem" }}>
                                <h4 style={{ fontSize: "0.7rem", textTransform: "uppercase", letterSpacing: "0.08em", color: "#f87171", marginBottom: "0.6rem" }}>
                                    ⚠ AI Violations ({aiViolations.length})
                                </h4>
                                <div style={{ display: "flex", flexDirection: "column", gap: "0.45rem" }}>
                                    {aiViolations.map((v: any, i: number) => (
                                        <div key={i} style={{
                                            padding: "0.6rem 0.8rem",
                                            borderLeft: `3px solid ${(v.severity || "").toLowerCase() === "high" ? "#ef4444" : (v.severity || "").toLowerCase() === "medium" ? "#f59e0b" : "#6366f1"}`,
                                            background: "rgba(0,0,0,0.22)", borderRadius: "0 0.45rem 0.45rem 0"
                                        }}>
                                            <div style={{ display: "flex", alignItems: "center", gap: "0.45rem", marginBottom: "0.4rem" }}>
                                                <SeverityBadge severity={v.severity || "medium"} />
                                            </div>
                                            <div style={{ fontSize: "0.8rem", color: "#fca5a5", lineHeight: 1.5, marginBottom: "0.3rem" }}>
                                                <strong>Observation:</strong> {v.observation || v.description}
                                            </div>
                                            {v.expert_reasoning && (
                                                <div style={{ fontSize: "0.75rem", color: "#cbd5e1", lineHeight: 1.5, fontStyle: "italic", marginBottom: "0.3rem" }}>
                                                    <strong>Expert Reasoning:</strong> {v.expert_reasoning}
                                                </div>
                                            )}
                                            {v.suggested_fix && (
                                                <div style={{ fontSize: "0.75rem", color: "#a7f3d0", lineHeight: 1.5 }}>
                                                    <strong>Fix:</strong> {v.suggested_fix}
                                                </div>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* Deterministic Errors */}
                        {deterministicErrors.length > 0 && (
                            <div style={{ marginBottom: "1rem" }}>
                                <h4 style={{ fontSize: "0.7rem", textTransform: "uppercase", letterSpacing: "0.08em", color: "#fb923c", marginBottom: "0.6rem" }}>
                                    📋 Rule Errors ({deterministicErrors.length})
                                </h4>
                                <div style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}>
                                    {deterministicErrors.map((e: string, i: number) => (
                                        <div key={i} style={{ padding: "0.45rem 0.7rem", borderLeft: "2px solid #fb923c", background: "rgba(251,146,60,0.05)", borderRadius: "0 0.35rem 0.35rem 0", fontSize: "0.8rem", color: "#fdba74" }}>{e}</div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* Warnings */}
                        {warnings.length > 0 && (
                            <div style={{ marginBottom: "0.5rem" }}>
                                <h4 style={{ fontSize: "0.7rem", textTransform: "uppercase", letterSpacing: "0.08em", color: "#fbbf24", marginBottom: "0.6rem" }}>
                                    ⚡ Warnings ({warnings.length})
                                </h4>
                                <div style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}>
                                    {warnings.map((w: string, i: number) => (
                                        <div key={i} style={{ padding: "0.45rem 0.7rem", borderLeft: "2px solid #f59e0b", background: "rgba(245,158,11,0.05)", borderRadius: "0 0.35rem 0.35rem 0", fontSize: "0.8rem", color: "#fde68a" }}>{w}</div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {aiViolations.length === 0 && deterministicErrors.length === 0 && warnings.length === 0 && (
                            <div style={{ textAlign: "center", color: "#34d399", padding: "2rem", fontSize: "0.9rem" }}>✓ No violations found</div>
                        )}

                        {/* Skipped Rules (domain mismatch) */}
                        {skippedRules.length > 0 && (
                            <div style={{ marginTop: "0.75rem" }}>
                                <button onClick={() => setShowSkipped(!showSkipped)} style={{
                                    background: "none", border: "none", cursor: "pointer", padding: "0.4rem 0",
                                    display: "flex", alignItems: "center", gap: "0.4rem", width: "100%"
                                }}>
                                    <span style={{ fontSize: "0.7rem", textTransform: "uppercase", letterSpacing: "0.08em", color: "#64748b" }}>
                                        {showSkipped ? "▾" : "▸"} Skipped Rules — Domain Mismatch ({skippedRules.length})
                                    </span>
                                </button>
                                {showSkipped && (
                                    <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem", marginTop: "0.4rem" }}>
                                        {skippedRules.map((r: any, i: number) => (
                                            <div key={i} style={{
                                                padding: "0.4rem 0.7rem", borderLeft: "2px solid #334155",
                                                background: "rgba(0,0,0,0.15)", borderRadius: "0 0.35rem 0.35rem 0",
                                                fontSize: "0.78rem", color: "#94a3b8"
                                            }}>
                                                <code style={{ fontSize: "0.66rem", color: "#64748b", background: "rgba(255,255,255,0.04)", padding: "0.1rem 0.3rem", borderRadius: "0.2rem" }}>
                                                    {r.rule_path}
                                                </code>
                                                <span style={{ marginLeft: "0.5rem" }}>{r.reason}</span>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                )}

                {/* ═══════════════ TAB: DECISION FLOW ═══════════════ */}
                {activeTab === "decision" && decisionFlow && (
                    <div style={{ maxHeight: "380px", overflowY: "auto" }}>

                        {/* Risk Classification Banner */}
                        <div style={{
                            padding: "0.7rem 1rem", borderRadius: "0.6rem", marginBottom: "1rem",
                            background: decisionFlow.risk === "HIGH" ? "rgba(16,185,129,0.08)" : decisionFlow.risk === "MEDIUM" ? "rgba(245,158,11,0.08)" : "rgba(239,68,68,0.08)",
                            border: `1px solid ${decisionFlow.risk === "HIGH" ? "rgba(16,185,129,0.25)" : decisionFlow.risk === "MEDIUM" ? "rgba(245,158,11,0.25)" : "rgba(239,68,68,0.25)"}`,
                            display: "flex", alignItems: "center", justifyContent: "space-between"
                        }}>
                            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                                <span style={{ fontSize: "1.3rem" }}>
                                    {decisionFlow.risk === "HIGH" ? "🟢" : decisionFlow.risk === "MEDIUM" ? "🟡" : "🔴"}
                                </span>
                                <div>
                                    <div style={{
                                        fontWeight: 700, fontSize: "0.88rem",
                                        color: decisionFlow.risk === "HIGH" ? "#34d399" : decisionFlow.risk === "MEDIUM" ? "#fbbf24" : "#f87171"
                                    }}>
                                        {decisionFlow.action === "safe_apply" ? "Safe Apply — All Rules" :
                                            decisionFlow.action === "selective_apply" ? "Selective Apply — With Warnings" :
                                                "Enforced Apply — Static Alignment"}
                                    </div>
                                    <div style={{ fontSize: "0.72rem", color: "#94a3b8", marginTop: "0.15rem" }}>
                                        Compatibility Score: {Math.round(decisionFlow.score)}/100
                                    </div>
                                </div>
                            </div>
                            <div style={{
                                padding: "0.3rem 0.9rem", borderRadius: "2rem", fontSize: "0.75rem", fontWeight: 800,
                                background: decisionFlow.risk === "HIGH" ? "rgba(16,185,129,0.08)" : decisionFlow.risk === "MEDIUM" ? "rgba(245,158,11,0.08)" : "rgba(239,68,68,0.08)",
                                color: decisionFlow.risk === "HIGH" ? "#34d399" : decisionFlow.risk === "MEDIUM" ? "#fbbf24" : "#f87171",
                                border: `1px solid ${decisionFlow.risk === "HIGH" ? "rgba(16,185,129,0.25)" : decisionFlow.risk === "MEDIUM" ? "rgba(245,158,11,0.25)" : "rgba(239,68,68,0.25)"}`
                            }}>
                                {decisionFlow.risk}
                            </div>
                        </div>

                        {/* Compatibility Dimensions */}
                        {decisionFlow.compatibility?.dimensions && (
                            <div style={{ marginBottom: "1.1rem" }}>
                                <h4 style={{ fontSize: "0.7rem", textTransform: "uppercase", letterSpacing: "0.08em", color: "#8b5cf6", marginBottom: "0.6rem" }}>
                                    📊 Compatibility Dimensions
                                </h4>
                                {[
                                    { key: "presence", label: "Structure Presence", weight: "40%" },
                                    { key: "order", label: "Sequence Fidelity", weight: "25%" },
                                    { key: "hierarchy", label: "Hierarchy Depth", weight: "25%" },
                                    { key: "completeness", label: "Completeness", weight: "10%" },
                                ].map(dim => {
                                    const val = decisionFlow.compatibility.dimensions[dim.key] ?? 0;
                                    const barColor = val >= 75 ? "#10b981" : val >= 40 ? "#f59e0b" : "#ef4444";
                                    return (
                                        <div key={dim.key} style={{ marginBottom: "0.5rem" }}>
                                            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.2rem" }}>
                                                <span style={{ fontSize: "0.75rem", color: "#cbd5e1" }}>{dim.label}</span>
                                                <span style={{ fontSize: "0.68rem", color: "#94a3b8" }}>
                                                    {Math.round(val)}/100 <span style={{ color: "#64748b" }}>({dim.weight})</span>
                                                </span>
                                            </div>
                                            <div style={{ height: "6px", background: "rgba(255,255,255,0.06)", borderRadius: "3px", overflow: "hidden" }}>
                                                <div style={{
                                                    height: "100%", width: `${val}%`, borderRadius: "3px",
                                                    background: barColor, transition: "width 0.6s ease"
                                                }} />
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        )}

                        {/* ── Expert Evaluation ── */}
                        {renderExpertEvaluation(decisionFlow.ai_evaluation || inner.ai_evaluation)}

                        {/* Rule Selection Cards */}
                        {decisionFlow.rule_selection && (
                            <div style={{ marginBottom: "1rem" }}>
                                <h4 style={{ fontSize: "0.7rem", textTransform: "uppercase", letterSpacing: "0.08em", color: "#8b5cf6", marginBottom: "0.6rem" }}>
                                    🔐 Rule Classification
                                </h4>
                                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "0.5rem" }}>
                                    {/* Safe */}
                                    <div style={{ padding: "0.6rem", borderRadius: "0.5rem", background: "rgba(16,185,129,0.06)", border: "1px solid rgba(16,185,129,0.15)" }}>
                                        <div style={{ fontSize: "0.68rem", fontWeight: 700, color: "#34d399", marginBottom: "0.35rem", display: "flex", alignItems: "center", gap: "0.3rem" }}>
                                            ✅ Safe <span style={{ fontSize: "0.62rem", fontWeight: 400, color: "#6ee7b7" }}>({(decisionFlow.rule_selection.safe_rules || []).length})</span>
                                        </div>
                                        <div style={{ fontSize: "0.68rem", color: "#94a3b8", lineHeight: 1.5 }}>
                                            {(decisionFlow.rule_selection.safe_rules || []).slice(0, 4).map((r: any, i: number) => (
                                                <div key={i} style={{ padding: "0.15rem 0", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>• {r.description?.substring(0, 50) || r.rule_path}</div>
                                            ))}
                                            {(decisionFlow.rule_selection.safe_rules || []).length > 4 && (
                                                <div style={{ color: "#64748b", fontStyle: "italic", marginTop: "0.2rem" }}>+{(decisionFlow.rule_selection.safe_rules || []).length - 4} more</div>
                                            )}
                                        </div>
                                    </div>
                                    {/* Conditional */}
                                    <div style={{ padding: "0.6rem", borderRadius: "0.5rem", background: "rgba(245,158,11,0.06)", border: "1px solid rgba(245,158,11,0.15)" }}>
                                        <div style={{ fontSize: "0.68rem", fontWeight: 700, color: "#fbbf24", marginBottom: "0.35rem", display: "flex", alignItems: "center", gap: "0.3rem" }}>
                                            ⚠️ Conditional <span style={{ fontSize: "0.62rem", fontWeight: 400, color: "#fde68a" }}>({(decisionFlow.rule_selection.conditional_rules || []).length})</span>
                                        </div>
                                        <div style={{ fontSize: "0.68rem", color: "#94a3b8", lineHeight: 1.5 }}>
                                            {(decisionFlow.rule_selection.conditional_rules || []).slice(0, 4).map((r: any, i: number) => (
                                                <div key={i} style={{ padding: "0.15rem 0", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>• {r.description?.substring(0, 50) || r.rule_path}</div>
                                            ))}
                                            {(decisionFlow.rule_selection.conditional_rules || []).length > 4 && (
                                                <div style={{ color: "#64748b", fontStyle: "italic", marginTop: "0.2rem" }}>+{(decisionFlow.rule_selection.conditional_rules || []).length - 4} more</div>
                                            )}
                                        </div>
                                    </div>
                                    {/* Forbidden */}
                                    <div style={{ padding: "0.6rem", borderRadius: "0.5rem", background: "rgba(239,68,68,0.06)", border: "1px solid rgba(239,68,68,0.15)" }}>
                                        <div style={{ fontSize: "0.68rem", fontWeight: 700, color: "#f87171", marginBottom: "0.35rem", display: "flex", alignItems: "center", gap: "0.3rem" }}>
                                            🚫 Forbidden <span style={{ fontSize: "0.62rem", fontWeight: 400, color: "#fca5a5" }}>({(decisionFlow.rule_selection.forbidden_rules || []).length})</span>
                                        </div>
                                        <div style={{ fontSize: "0.68rem", color: "#94a3b8", lineHeight: 1.5 }}>
                                            {(decisionFlow.rule_selection.forbidden_rules || []).slice(0, 4).map((r: any, i: number) => (
                                                <div key={i} style={{ padding: "0.15rem 0", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>• {r.description?.substring(0, 50) || r.rule_path}</div>
                                            ))}
                                            {(decisionFlow.rule_selection.forbidden_rules || []).length > 4 && (
                                                <div style={{ color: "#64748b", fontStyle: "italic", marginTop: "0.2rem" }}>+{(decisionFlow.rule_selection.forbidden_rules || []).length - 4} more</div>
                                            )}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* Decision Flow Warnings */}
                        {(decisionFlow.warnings || []).length > 0 && (
                            <div style={{ marginBottom: "0.75rem" }}>
                                <h4 style={{ fontSize: "0.7rem", textTransform: "uppercase", letterSpacing: "0.08em", color: "#fbbf24", marginBottom: "0.5rem" }}>
                                    ⚡ Conditional Warnings
                                </h4>
                                <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem" }}>
                                    {(decisionFlow.warnings || []).map((w: any, i: number) => (
                                        <div key={i} style={{
                                            padding: "0.4rem 0.7rem", borderLeft: "2px solid #f59e0b",
                                            background: "rgba(245,158,11,0.05)", borderRadius: "0 0.35rem 0.35rem 0",
                                            fontSize: "0.78rem", color: "#fde68a"
                                        }}>
                                            <code style={{ fontSize: "0.66rem", color: "#fbbf24", background: "rgba(255,255,255,0.06)", padding: "0.1rem 0.3rem", borderRadius: "0.2rem" }}>
                                                {w.rule_path}
                                            </code>
                                            <span style={{ marginLeft: "0.4rem" }}>{w.message || w.description}</span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* Action message */}
                        {decisionFlow.action === "enforced_apply" && (
                            <div style={{
                                padding: "1rem", borderRadius: "0.5rem", textAlign: "center",
                                background: "rgba(245,158,11,0.06)", border: "1px solid rgba(245,158,11,0.15)"
                            }}>
                                <div style={{ fontSize: "1.5rem", marginBottom: "0.4rem" }}>⚠️</div>
                                <div style={{ fontWeight: 700, color: "#fbbf24", fontSize: "0.88rem" }}>Low Compatibility Mode</div>
                                <div style={{ color: "#94a3b8", fontSize: "0.78rem", marginTop: "0.3rem" }}>
                                    Compatibility is low. Alignment will be applied using strict structural placeholders.
                                </div>
                            </div>
                        )}

                        {fixResult && (
                            <div style={{ textAlign: "center", padding: "0.5rem", display: "flex", gap: "0.5rem", justifyContent: "center" }}>
                                {deviations.length > 0 && (
                                    <button onClick={() => setActiveTab("deviations")}
                                        style={{
                                            background: "rgba(245,158,11,0.15)", border: "1px solid rgba(245,158,11,0.3)", color: "#fbbf24",
                                            padding: "0.45rem 1.2rem", borderRadius: "0.5rem", cursor: "pointer", fontWeight: 600,
                                            fontSize: "0.82rem"
                                        }}>
                                        📋 View {deviations.length} Deviations
                                    </button>
                                )}
                                <button onClick={() => setActiveTab("preview")}
                                    style={{
                                        background: "linear-gradient(135deg, #8b5cf6, #6366f1)", border: "none", color: "white",
                                        padding: "0.45rem 1.2rem", borderRadius: "0.5rem", cursor: "pointer", fontWeight: 600,
                                        fontSize: "0.82rem"
                                    }}>
                                    View Transformed Document →
                                </button>
                            </div>
                        )}
                    </div>
                )}

                {/* ═══════════════ TAB: DEVIATIONS ═══════════════ */}
                {activeTab === "deviations" && deviations.length > 0 && (
                    <div style={{ maxHeight: "380px", overflowY: "auto" }}>

                        {/* Change Summary */}
                        {changeSummary && (
                            <div style={{
                                padding: "0.65rem 1rem", borderRadius: "0.5rem", marginBottom: "1rem",
                                background: "rgba(99,102,241,0.08)", border: "1px solid rgba(99,102,241,0.2)"
                            }}>
                                <div style={{ fontSize: "0.68rem", textTransform: "uppercase", letterSpacing: "0.08em", color: "#a5b4fc", marginBottom: "0.3rem", fontWeight: 700 }}>Change Summary</div>
                                <div style={{ fontSize: "0.8rem", color: "#c7d2fe", lineHeight: 1.5 }}>{changeSummary}</div>
                            </div>
                        )}

                        {/* Severity counts */}
                        <div style={{ display: "flex", gap: "0.45rem", marginBottom: "1rem", flexWrap: "wrap" }}>
                            {(() => {
                                const cosCount = deviations.filter((d: any) => d.severity === "cosmetic").length;
                                const strCount = deviations.filter((d: any) => d.severity === "structural").length;
                                const semCount = deviations.filter((d: any) => d.severity === "semantic").length;
                                return (
                                    <>
                                        {cosCount > 0 && <div style={{ padding: "0.25rem 0.7rem", borderRadius: "2rem", fontSize: "0.73rem", fontWeight: 700, background: "rgba(59,130,246,0.12)", color: "#60a5fa", border: "1px solid rgba(59,130,246,0.3)" }}>🔵 {cosCount} Cosmetic</div>}
                                        {strCount > 0 && <div style={{ padding: "0.25rem 0.7rem", borderRadius: "2rem", fontSize: "0.73rem", fontWeight: 700, background: "rgba(245,158,11,0.12)", color: "#fbbf24", border: "1px solid rgba(245,158,11,0.3)" }}>🟡 {strCount} Structural</div>}
                                        {semCount > 0 && <div style={{ padding: "0.25rem 0.7rem", borderRadius: "2rem", fontSize: "0.73rem", fontWeight: 700, background: "rgba(239,68,68,0.12)", color: "#f87171", border: "1px solid rgba(239,68,68,0.3)" }}>🔴 {semCount} Semantic</div>}
                                    </>
                                );
                            })()}
                        </div>

                        {/* Deviation List */}
                        <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                            {deviations.map((dev: any, i: number) => {
                                const sevColor = dev.severity === "semantic" ? "#ef4444" : dev.severity === "structural" ? "#f59e0b" : "#3b82f6";
                                return (
                                    <div key={i} style={{
                                        padding: "0.7rem 0.9rem", borderLeft: `3px solid ${sevColor}`,
                                        background: "rgba(0,0,0,0.22)", borderRadius: "0 0.5rem 0.5rem 0"
                                    }}>
                                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.35rem" }}>
                                            <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
                                                <span style={{
                                                    padding: "0.1rem 0.5rem", borderRadius: "2rem", fontSize: "0.62rem", fontWeight: 700,
                                                    textTransform: "uppercase", letterSpacing: "0.06em",
                                                    background: dev.severity === "semantic" ? "rgba(239,68,68,0.15)" : dev.severity === "structural" ? "rgba(245,158,11,0.15)" : "rgba(59,130,246,0.12)",
                                                    color: sevColor, border: `1px solid ${sevColor}40`
                                                }}>
                                                    {dev.severity || "cosmetic"}
                                                </span>
                                                <code style={{ fontSize: "0.66rem", color: "#94a3b8", background: "rgba(255,255,255,0.06)", padding: "0.1rem 0.35rem", borderRadius: "0.25rem" }}>
                                                    {dev.location}
                                                </code>
                                            </div>
                                            {dev.rule_reference && (
                                                <code style={{ fontSize: "0.6rem", color: "#64748b", background: "rgba(255,255,255,0.04)", padding: "0.1rem 0.3rem", borderRadius: "0.2rem" }}>
                                                    {dev.rule_reference}
                                                </code>
                                            )}
                                        </div>
                                        {/* Original → Changed */}
                                        <div style={{ display: "grid", gridTemplateColumns: "1fr auto 1fr", gap: "0.4rem", alignItems: "flex-start", marginBottom: "0.3rem" }}>
                                            <div style={{ fontSize: "0.73rem", color: "#fca5a5", background: "rgba(239,68,68,0.06)", padding: "0.3rem 0.5rem", borderRadius: "0.3rem", lineHeight: 1.4, wordBreak: "break-word" }}>
                                                <span style={{ fontSize: "0.6rem", color: "#ef4444", fontWeight: 700, display: "block", marginBottom: "0.15rem" }}>ORIGINAL</span>
                                                {dev.original_text}
                                            </div>
                                            <span style={{ color: "#64748b", fontSize: "1rem", alignSelf: "center" }}>→</span>
                                            <div style={{ fontSize: "0.73rem", color: "#86efac", background: "rgba(16,185,129,0.06)", padding: "0.3rem 0.5rem", borderRadius: "0.3rem", lineHeight: 1.4, wordBreak: "break-word" }}>
                                                <span style={{ fontSize: "0.6rem", color: "#10b981", fontWeight: 700, display: "block", marginBottom: "0.15rem" }}>CHANGED TO</span>
                                                {dev.changed_to}
                                            </div>
                                        </div>
                                        {/* Reason */}
                                        <div style={{ fontSize: "0.72rem", color: "#94a3b8", lineHeight: 1.5, fontStyle: "italic" }}>
                                            💡 {dev.reason}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>

                        {/* Preserved Items */}
                        {preservedItems.length > 0 && (
                            <div style={{ marginTop: "1rem" }}>
                                <button onClick={() => setShowPreserved(!showPreserved)} style={{
                                    background: "none", border: "none", cursor: "pointer", padding: "0.4rem 0",
                                    display: "flex", alignItems: "center", gap: "0.4rem", width: "100%"
                                }}>
                                    <span style={{ fontSize: "0.7rem", textTransform: "uppercase", letterSpacing: "0.08em", color: "#34d399" }}>
                                        {showPreserved ? "▾" : "▸"} Preserved Items — Not Changed ({preservedItems.length})
                                    </span>
                                </button>
                                {showPreserved && (
                                    <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem", marginTop: "0.4rem" }}>
                                        {preservedItems.map((item: string, i: number) => (
                                            <div key={i} style={{
                                                padding: "0.4rem 0.7rem", borderLeft: "2px solid #10b981",
                                                background: "rgba(16,185,129,0.04)", borderRadius: "0 0.35rem 0.35rem 0",
                                                fontSize: "0.78rem", color: "#86efac"
                                            }}>
                                                ✓ {item}
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                )}

                {/* ═══════════════ TAB: PREVIEW ═══════════════ */}
                {activeTab === "preview" && fixResult && (
                    <div>
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.75rem" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                                <span style={{ fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.08em", color: "#34d399" }}>
                                    ✨ Full AI-Fixed Document
                                </span>
                                <button onClick={() => setIsFullscreen(true)} className="btn-icon" title="Full Screen"
                                    style={{
                                        background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.15)",
                                        color: "#94a3b8", padding: "0.2rem 0.6rem", borderRadius: "0.4rem", fontSize: "0.7rem", cursor: "pointer",
                                        display: "flex", alignItems: "center", gap: "0.3rem", transition: "all 0.2s"
                                    }}>
                                    ⛶ Full Screen
                                </button>
                                <button onClick={handleCopy} className="btn-icon" title="Copy to Clipboard"
                                    style={{
                                        background: copied ? "rgba(16,185,129,0.2)" : "rgba(255,255,255,0.05)",
                                        border: `1px solid ${copied ? "#10b981" : "rgba(255,255,255,0.15)"}`,
                                        color: copied ? "#34d399" : "#94a3b8",
                                        padding: "0.2rem 0.6rem", borderRadius: "0.4rem", fontSize: "0.7rem", cursor: "pointer",
                                        display: "flex", alignItems: "center", gap: "0.3rem", transition: "all 0.2s"
                                    }}>
                                    {copied ? "✓ Copied!" : "📋 Copy All"}
                                </button>
                            </div>
                            <span style={{ fontSize: "0.7rem", color: "#64748b" }}>
                                {fixResult.fixed_content.split("\n").length} lines
                            </span>
                        </div>
                        <div style={{
                            background: "rgba(0,0,0,0.35)", border: "1px solid rgba(16,185,129,0.2)", borderRadius: "0.6rem",
                            padding: "1rem", color: "#86efac", height: "340px", overflowY: "auto",
                            overflowX: "auto", lineHeight: 1.65
                        }}>
                            <div className="markdown-preview" style={{ fontSize: "0.85rem", color: "#e2e8f0" }}>
                                <ReactMarkdown
                                    remarkPlugins={[remarkGfm]}
                                    urlTransform={(value: string) => value}
                                    components={{
                                        img: ({ node, ...props }) => (
                                            <img
                                                {...props}
                                                style={{
                                                    maxWidth: "100%",
                                                    height: "auto",
                                                    borderRadius: "0.4rem",
                                                    margin: "1.5rem 0",
                                                    display: "block",
                                                    border: "1px solid rgba(16,185,129,0.2)",
                                                    boxShadow: "0 4px 20px rgba(0,0,0,0.4)"
                                                }}
                                            />
                                        )
                                    }}
                                >
                                    {fixResult.fixed_content}
                                </ReactMarkdown>
                            </div>
                        </div>
                    </div>
                )}

                {/* ═══════════════ FULL SCREEN MODAL ═══════════════ */}
                {isFullscreen && fixResult && activeTab === "preview" && (
                    <div style={{
                        position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
                        backgroundColor: "rgba(15, 23, 42, 0.95)", zIndex: 9999,
                        display: "flex", flexDirection: "column", padding: "2rem"
                    }}>
                        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "1rem" }}>
                            <h2 style={{ color: "#f8fafc", margin: 0 }}>Full Screen Preview</h2>
                            <div style={{ display: "flex", gap: "1rem" }}>
                                <button onClick={handleCopy} className="btn-icon" title="Copy to Clipboard"
                                    style={{
                                        background: copied ? "rgba(16,185,129,0.2)" : "rgba(255,255,255,0.1)",
                                        border: `1px solid ${copied ? "#10b981" : "rgba(255,255,255,0.2)"}`,
                                        color: copied ? "#34d399" : "#f8fafc", padding: "0.5rem 1rem", borderRadius: "0.4rem",
                                        cursor: "pointer", display: "flex", alignItems: "center", gap: "0.5rem"
                                    }}>
                                    {copied ? "✓ Copied!" : "📋 Copy"}
                                </button>
                                <button onClick={() => setIsFullscreen(false)} style={{
                                    background: "rgba(239, 68, 68, 0.2)", border: "1px solid rgba(239, 68, 68, 0.5)",
                                    color: "#fca5a5", padding: "0.5rem 1rem", borderRadius: "0.4rem", cursor: "pointer"
                                }}>
                                    ✖ Close
                                </button>
                            </div>
                        </div>
                        <div style={{
                            background: "#1e293b", border: "1px solid #334155", borderRadius: "0.5rem",
                            padding: "2rem", overflowY: "auto", flex: 1, boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.5)"
                        }}>
                            <div className="markdown-preview" style={{ fontSize: "1rem", color: "#e2e8f0", lineHeight: 1.8, maxWidth: "900px", margin: "0 auto" }}>
                                <ReactMarkdown
                                    remarkPlugins={[remarkGfm]}
                                    urlTransform={(value: string) => value}
                                    components={{
                                        img: ({ node, ...props }) => (
                                            <span style={{ display: "block", margin: "2rem 0", textAlign: "center" }}>
                                                <img
                                                    {...props}
                                                    style={{
                                                        maxWidth: "100%",
                                                        height: "auto",
                                                        borderRadius: "0.8rem",
                                                        display: "inline-block",
                                                        border: "1px solid rgba(255,255,255,0.1)",
                                                        boxShadow: "0 10px 30px rgba(0,0,0,0.5)"
                                                    }}
                                                />
                                                {props.alt && (
                                                    <span style={{ display: "block", fontSize: "0.8rem", color: "#94a3b8", marginTop: "0.5rem", fontStyle: "italic" }}>
                                                        {props.alt}
                                                    </span>
                                                )}
                                            </span>
                                        )
                                    }}
                                >
                                    {fixResult.fixed_content}
                                </ReactMarkdown>
                            </div>
                        </div>
                    </div>
                )}

                {/* ═══════════════ TAB: DIFF ═══════════════ */}
                {activeTab === "diff" && fixResult && (
                    <div>
                        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", marginBottom: "0.75rem", flexWrap: "wrap" }}>
                            <span style={{ fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.08em", color: "#94a3b8" }}>
                                Changes vs Original
                            </span>
                            <span style={{ padding: "0.15rem 0.6rem", borderRadius: "1rem", fontSize: "0.7rem", fontWeight: 700, background: "rgba(16,185,129,0.1)", color: "#34d399", border: "1px solid rgba(16,185,129,0.25)" }}>
                                +{addedCount} added
                            </span>
                            <span style={{ padding: "0.15rem 0.6rem", borderRadius: "1rem", fontSize: "0.7rem", fontWeight: 700, background: "rgba(239,68,68,0.1)", color: "#f87171", border: "1px solid rgba(239,68,68,0.25)" }}>
                                -{removedCount} removed
                            </span>
                        </div>

                        {fixResult.original_content ? (
                            <div style={{ height: "340px", overflowY: "auto", border: "1px solid rgba(255,255,255,0.08)", borderRadius: "0.6rem", fontFamily: "monospace", fontSize: "0.73rem", lineHeight: 1.6 }}>
                                {diffLines.map((line, i) => {
                                    const isAdded = line.type === "added";
                                    const isRemoved = line.type === "removed";
                                    return (
                                        <div key={i} style={{
                                            display: "flex", alignItems: "flex-start",
                                            background: isAdded ? "rgba(16,185,129,0.1)" : isRemoved ? "rgba(239,68,68,0.1)" : "transparent",
                                            borderLeft: `3px solid ${isAdded ? "#10b981" : isRemoved ? "#ef4444" : "transparent"}`,
                                            minHeight: "1.6em"
                                        }}>
                                            {/* Gutter sign */}
                                            <div style={{
                                                width: "22px", flexShrink: 0, textAlign: "center", paddingTop: "0.1rem",
                                                color: isAdded ? "#34d399" : isRemoved ? "#f87171" : "#334155",
                                                fontWeight: 700, fontSize: "0.8rem", userSelect: "none"
                                            }}>
                                                {isAdded ? "+" : isRemoved ? "−" : " "}
                                            </div>
                                            {/* Line number */}
                                            <div style={{
                                                width: "36px", flexShrink: 0, paddingRight: "0.5rem", textAlign: "right",
                                                color: "#334155", paddingTop: "0.1rem", userSelect: "none"
                                            }}>
                                                {line.lineNo ?? ""}
                                            </div>
                                            {/* Content */}
                                            <div style={{
                                                flex: 1, padding: "0.05rem 0.5rem 0.05rem 0",
                                                color: isAdded ? "#86efac" : isRemoved ? "#fca5a5" : "#cbd5e1",
                                                whiteSpace: "pre", overflowX: "visible"
                                            }}>
                                                {line.text || " "}
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        ) : (
                            <div style={{
                                height: "340px", overflowY: "auto", border: "1px solid rgba(255,255,255,0.08)", borderRadius: "0.6rem",
                                padding: "1rem", display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: "0.5rem"
                            }}>
                                <span style={{ color: "#64748b", fontSize: "0.85rem" }}>Original content not available for diff.</span>
                                <span style={{ color: "#475569", fontSize: "0.75rem" }}>Switch to the Preview tab to view the full fixed document.</span>
                            </div>
                        )}
                    </div>
                )}

                {/* ── Footer ── */}
                <div style={{
                    display: "flex", gap: "0.5rem", justifyContent: "flex-end", paddingTop: "1rem",
                    borderTop: "1px solid rgba(255,255,255,0.07)", marginTop: "1rem"
                }}>
                    {fixResult && (
                        <div style={{ display: "flex", gap: "0.5rem" }}>
                            <button onClick={handleDownloadPDF}
                                style={{
                                    background: "rgba(16,185,129,0.15)",
                                    border: "1px solid rgba(16,185,129,0.4)",
                                    color: "#34d399",
                                    padding: "0.5rem 1.1rem", borderRadius: "0.5rem", cursor: "pointer", fontWeight: 600,
                                    fontSize: "0.88rem", display: "flex", alignItems: "center", gap: "0.4rem", transition: "all 0.2s"
                                }}>
                                📥 Download Fixed PDF
                            </button>
                            <button onClick={handleCopy}
                                style={{
                                    background: copied ? "rgba(16,185,129,0.15)" : "rgba(99,102,241,0.15)",
                                    border: `1px solid ${copied ? "#10b981" : "rgba(99,102,241,0.4)"}`,
                                    color: copied ? "#34d399" : "#a5b4fc",
                                    padding: "0.5rem 1.1rem", borderRadius: "0.5rem", cursor: "pointer", fontWeight: 600,
                                    fontSize: "0.88rem", display: "flex", alignItems: "center", gap: "0.4rem", transition: "all 0.2s"
                                }}>
                                {copied ? "✓ Copied!" : "📋 Copy Content"}
                            </button>
                        </div>
                    )}
                    {!decisionFlow && !fixResult && !isCompliant && (
                        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                            <select
                                value={competenceLevel}
                                onChange={(e) => setCompetenceLevel(e.target.value)}
                                style={{
                                    background: "rgba(255,255,255,0.08)", border: "1px solid rgba(255,255,255,0.15)",
                                    color: "#e2e8f0", padding: "0.45rem 0.8rem", borderRadius: "0.5rem",
                                    fontSize: "0.82rem", outline: "none", cursor: "pointer"
                                }}
                            >
                                <option value="general" style={{ background: "#1e293b", color: "#e2e8f0" }}>General Audience</option>
                                <option value="operator" style={{ background: "#1e293b", color: "#e2e8f0" }}>Operator (Safety & Basics)</option>
                                <option value="technician" style={{ background: "#1e293b", color: "#e2e8f0" }}>Technician (Maintenance)</option>
                                <option value="engineer" style={{ background: "#1e293b", color: "#e2e8f0" }}>Engineer (Dense & Detailed)</option>
                            </select>
                            <button onClick={handleFix} disabled={fixLoading}
                                style={{
                                    background: "linear-gradient(135deg,#8b5cf6,#6366f1)", border: "none", color: "white",
                                    padding: "0.5rem 1.1rem", borderRadius: "0.5rem", cursor: "pointer", fontWeight: 600,
                                    fontSize: "0.88rem", display: "flex", alignItems: "center", gap: "0.4rem",
                                    opacity: fixLoading ? 0.7 : 1
                                }}>
                                {fixLoading ? "⏳ Compiling Structural Alignment…" : "⚡ Apply Structural Alignment"}
                            </button>
                        </div>
                    )}
                    <button className="btn btn-primary" onClick={onClose}>Close</button>
                </div>
            </div>

            <style>{`
        .modal-overlay {
          position: fixed; inset: 0; background: rgba(0,0,0,0.78);
          backdrop-filter: blur(8px); display: flex; align-items: center;
          justify-content: center; z-index: 2000; padding: 1.5rem;
        }
        .report-modal {
          width: 100%; max-width: 660px; max-height: 92vh; overflow-y: auto;
        }
        .score-badge-lg {
          padding: 0.4rem 1rem; border-radius: 2rem; font-size: 1.05rem;
          font-weight: 800; letter-spacing: -0.02em;
        }
        .score-pass { background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid rgba(16,185,129,0.3); }
        .score-fail { background: rgba(239,68,68,0.15); color: #f87171; border: 1px solid rgba(239,68,68,0.3); }
        .close-x {
          background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.15);
          color: #94a3b8; width: 30px; height: 30px; border-radius: 50%; cursor: pointer;
          font-size: 0.85rem; display: flex; align-items: center; justify-content: center;
        }
      `}</style>
        </div>
    );
}
