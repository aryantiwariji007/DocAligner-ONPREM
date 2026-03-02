"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";

interface StandardApplicationModalProps {
    standard: any;
    onClose: () => void;
    onSuccess: () => void;
}

export default function StandardApplicationModal({ standard, onClose, onSuccess }: StandardApplicationModalProps) {
    const [targetType, setTargetType] = useState<"DOCUMENT" | "FOLDER">("DOCUMENT");
    const [documents, setDocuments] = useState<any[]>([]);
    const [folders, setFolders] = useState<any[]>([]);
    const [selectedTargetId, setSelectedTargetId] = useState("");
    const [loading, setLoading] = useState(false);
    const [dataLoading, setDataLoading] = useState(false);

    const [versions, setVersions] = useState<any[]>([]);

    useEffect(() => {
        loadData();
        checkVersions();
    }, [targetType, standard.id]);

    const checkVersions = async () => {
        try {
            const v = await api.getStandardVersions(undefined, standard.id);
            setVersions(v);
        } catch (e) {
            console.error("Failed to load versions", e);
        }
    }

    const loadData = async () => {
        setDataLoading(true);
        try {
            if (targetType === "DOCUMENT") {
                const docs = await api.getDocuments();
                setDocuments(docs);
            } else {
                const flds = await api.getFolders();
                setFolders(flds);
            }
        } catch (e) {
            console.error("Failed to load targets", e);
        } finally {
            setDataLoading(false);
        }
    };

    const handleApply = async () => {
        if (!selectedTargetId) return;
        if (versions.length === 0) {
            alert("This standard has no active versions. Use the 'Promote' button on a document to create a reference version first.");
            return;
        }
        setLoading(true);
        try {
            if (targetType === "DOCUMENT") {
                await api.applyStandardToDocument(undefined, standard.id, selectedTargetId);
            } else {
                await api.applyStandardToFolder(undefined, standard.id, selectedTargetId);
            }
            alert(`Standard applied to ${targetType.toLowerCase()} successfully!`);
            onSuccess();
            onClose();
        } catch (e: any) {
            console.error(e);
            alert(e.message || "Failed to apply standard.");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="modal-overlay">
            <div className="modal-content glass-card">
                <h3>Apply Standard: {standard.name}</h3>
                <p style={{ fontSize: "0.875rem", color: "var(--text-secondary)", marginBottom: "1rem" }}>
                    Select a target to enforce this standard.
                </p>

                <div className="form-group">
                    <label>Target Type</label>
                    <div style={{ display: "flex", gap: "1rem", marginBottom: "1rem" }}>
                        <button
                            className={`btn ${targetType === "DOCUMENT" ? "btn-primary" : "btn-outline"}`}
                            onClick={() => { setTargetType("DOCUMENT"); setSelectedTargetId(""); }}
                        >
                            Single File
                        </button>
                        <button
                            className={`btn ${targetType === "FOLDER" ? "btn-primary" : "btn-outline"}`}
                            onClick={() => { setTargetType("FOLDER"); setSelectedTargetId(""); }}
                        >
                            Entire Folder
                        </button>
                    </div>
                </div>

                <div className="form-group">
                    <label>Select {targetType === "DOCUMENT" ? "Document" : "Folder"}</label>
                    <select
                        value={selectedTargetId}
                        onChange={(e) => setSelectedTargetId(e.target.value)}
                        disabled={dataLoading}
                    >
                        <option value="">-- Select Target --</option>
                        {targetType === "DOCUMENT" ? (
                            documents.map(d => (
                                <option key={d.id} value={d.id}>{d.filename}</option>
                            ))
                        ) : (
                            folders.map(f => (
                                <option key={f.id} value={f.id}>{f.name}</option>
                            ))
                        )}
                    </select>
                    {dataLoading && <small>Loading...</small>}
                </div>

                <div className="actions" style={{ marginTop: '1.5rem', display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                    <button className="btn btn-outline" onClick={onClose} disabled={loading}>Cancel</button>
                    <button className="btn btn-primary" onClick={handleApply} disabled={loading || !selectedTargetId}>
                        {loading ? "Applying..." : "Apply Standard"}
                    </button>
                </div>
            </div>
            <style jsx>{`
        .modal-overlay {
          position: fixed;
          top: 0; left: 0; right: 0; bottom: 0;
          background: rgba(0,0,0,0.6);
          display: flex;
          justify-content: center;
          align-items: center;
          z-index: 1000;
          backdrop-filter: blur(4px);
        }
        .modal-content {
          width: 450px;
          padding: 2rem;
          border: 1px solid rgba(255,255,255,0.1);
          box-shadow: 0 20px 50px rgba(0,0,0,0.3);
        }
      `}</style>
        </div>
    );
}
