"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import Link from "next/link";

export default function AuditPage() {
    const [logs, setLogs] = useState<any[]>([]);

    useEffect(() => {
        const fetchLogs = async () => {
            try {
                const data = await api.getAuditLogs();
                setLogs(data);
            } catch (e) {
                console.error("Audit log fetch failed:", e);
            }
        };
        fetchLogs();
        const interval = setInterval(fetchLogs, 10000);
        return () => clearInterval(interval);
    }, []);

    return (
        <main>
            <div className="header-actions">
                <h1>System Audit Logs</h1>
                <Link href="/" className="btn btn-outline">Back to Dashboard</Link>
            </div>

            <div className="glass-card">
                <table>
                    <thead>
                        <tr>
                            <th>Timestamp</th>
                            <th>Action</th>
                            <th>Target ID</th>
                            <th>Details</th>
                        </tr>
                    </thead>
                    <tbody>
                        {logs.map((log) => (
                            <tr key={log.id}>
                                <td style={{ fontSize: "0.8rem" }}>{new Date(log.timestamp).toLocaleString()}</td>
                                <td>
                                    <span className="status-badge status-pass" style={{ background: "rgba(99, 102, 241, 0.2)", color: "#818cf8" }}>
                                        {log.action}
                                    </span>
                                </td>
                                <td style={{ fontSize: "0.7rem", color: "var(--text-secondary)" }}>{log.target_id}</td>
                                <td style={{ fontSize: "0.8rem" }}>{JSON.stringify(log.details)}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </main>
    );
}
