"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";

interface AssignmentModalProps {
    type: "FOLDER" | "DOCUMENT";
    targetId: string;
    targetName: string;
    onClose: () => void;
    onSuccess: () => void;
}

export default function AssignmentModal({ type, targetId, targetName, onClose, onSuccess }: AssignmentModalProps) {
    const [standards, setStandards] = useState<any[]>([]);
    const [selectedStandardId, setSelectedStandardId] = useState("");
    const [versions, setVersions] = useState<any[]>([]);
    const [selectedVersionId, setSelectedVersionId] = useState("");
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        loadStandards();
    }, []);

    const loadStandards = async () => {
        try {
            const s = await api.getStandards();
            setStandards(s);
            if (s.length > 0) {
                // Automatically select first one? or wait user
            }
        } catch (e) {
            console.error(e);
            alert("Failed to load standards");
        }
    };

    // When standard selected, we should ideally fetch versions.
    // The API getStandards might return versions nested or we need another call?
    // Checking backend code... standards.py: read_standards returns list of Standard.
    // Standard model has versions relationship? Let's check Standard model in backend code if need be.
    // For now, let's assume getStandards returns enough info or we just use the ID if versions aren't exposed yet.
    // Wait, standard assignment needs standard_version_id.

    // Implementation Note: The current getStandards API only returns the Standard definition. 
    // We need an endpoint to get versions for a standard.
    // OR we can just pick the "latest" if the backend supports it, but the API expects `standard_version_id`.

    // Let's check if we have an API to get versions. 
    // Looking at standards.py... no explicit get_versions endpoint seen in previous cat.
    // But promote_document_to_standard creates a version.

    // I will implement a quick fetchVersions in this component effectively if I can, 
    // or I might need to update backend to include versions in the standard list.
    // Let's assume for this MVP we might need to add `versions` to the Standard response model or a new endpoint.

    // Actually, I'll update the backend to include versions in the `GET /standards/` response
    // OR add a `GET /standards/{id}/versions` endpoint.
    // Let's check the Standard model again to see if `versions` are loaded default. 
    // They are a relationship, so might be lazy loaded.

    // Strategy:
    // 1. I'll blindly attempt to see if `versions` are in the `standards` response.
    // 2. If not, I'll need to fix backend.

    /* 
      Current Plan: 
      - User selects Standard.
      - User selects Version (if available).
      - Submit.
    */

    const handleAssign = async () => {
        if (!selectedVersionId) {
            alert("Please select a version");
            return;
        }
        setLoading(true);
        try {
            await api.assignStandard(undefined, {
                target_id: targetId,
                target_type: type,
                standard_version_id: selectedVersionId
            });
            alert("Assigned successfully! Validations triggered.");
            onSuccess();
            onClose();
        } catch (e) {
            alert("Assignment failed");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="modal-overlay">
            <div className="modal-content glass-card">
                <h3>Assign Standard to {type === "FOLDER" ? "Folder" : "Document"}</h3>
                <p>Target: <strong>{targetName}</strong></p>

                <div className="form-group">
                    <label>Select Standard</label>
                    <select
                        value={selectedStandardId}
                        onChange={async (e) => {
                            const standardId = e.target.value;
                            setSelectedStandardId(standardId);
                            if (standardId) {
                                try {
                                    const v = await api.getStandardVersions(undefined, standardId);
                                    setVersions(v);
                                    if (v.length > 0) {
                                        setSelectedVersionId(v[0].id); // Default to latest (sorted desc by backend)
                                    } else {
                                        setSelectedVersionId("");
                                    }
                                } catch (err) {
                                    console.error("Failed to load versions", err);
                                    setVersions([]);
                                    setSelectedVersionId("");
                                }
                            } else {
                                setVersions([]);
                                setSelectedVersionId("");
                            }
                        }}
                    >
                        <option value="">-- Choose Standard --</option>
                        {standards.map(s => (
                            <option key={s.id} value={s.id}>{s.name}</option>
                        ))}
                    </select>
                </div>

                {selectedStandardId && (
                    <div className="form-group">
                        <label>Select Version</label>
                        <select value={selectedVersionId} onChange={(e) => setSelectedVersionId(e.target.value)}>
                            <option value="">-- Choose Version --</option>
                            {versions.map(v => (
                                <option key={v.id} value={v.id}>v{v.version_number} ({new Date(v.created_at).toLocaleDateString()})</option>
                            ))}
                            {versions.length === 0 && <option disabled>No versions found</option>}
                        </select>
                    </div>
                )}

                <div className="actions" style={{ marginTop: '1rem', display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                    <button className="btn btn-outline" onClick={onClose} disabled={loading}>Cancel</button>
                    <button className="btn btn-primary" onClick={handleAssign} disabled={loading || !selectedVersionId}>
                        {loading ? "Assigning..." : "Assign Standard"}
                    </button>
                </div>
            </div>
            <style jsx>{`
        .modal-overlay {
          position: fixed;
          top: 0; left: 0; right: 0; bottom: 0;
          background: rgba(0,0,0,0.5);
          display: flex;
          justify-content: center;
          align-items: center;
          z-index: 1000;
        }
        .modal-content {
          width: 400px;
          padding: 2rem;
        }
      `}</style>
        </div>
    );
}
