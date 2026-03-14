import { useEffect, useState } from 'react';
import { Shield, RefreshCcw, AlertTriangle, CheckCircle, Info, XCircle, Search } from 'lucide-react';
import { motion } from 'framer-motion';
import { cn } from '../../lib/utils';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8100';

interface AuditEntry {
    id: string;
    timestamp: string;
    event_type: string;
    action: string;
    severity: 'info' | 'warning' | 'error' | 'critical';
    summary: string;
    agent?: string;
    approved?: boolean;
    details?: string;
}

export function AuditLog() {
    const [entries, setEntries] = useState<AuditEntry[]>([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState<string>('all');
    const [searchQuery, setSearchQuery] = useState('');

    const fetchAudit = async () => {
        try {
            setLoading(true);
            const [healthRes, incidentRes] = await Promise.all([
                fetch(`${API_BASE}/healthz`).then(r => r.json()).catch(() => ({})),
                fetch(`${API_BASE}/v1/iterations/incidents`).then(r => r.json()).catch(() => ({ incidents: [] }))
            ]);

            const combined: AuditEntry[] = [];

            // Add incidents from self-healing
            if (incidentRes.incidents) {
                incidentRes.incidents.forEach((inc: Record<string, string>, i: number) => {
                    combined.push({
                        id: `inc_${i}`,
                        timestamp: inc.timestamp || new Date().toISOString(),
                        event_type: 'incident',
                        action: inc.type || 'self_heal',
                        severity: 'warning',
                        summary: inc.summary || inc.error || 'Self-healing event',
                        details: inc.resolution
                    });
                });
            }

            // Add governor audit from health data
            if (healthRes.governor_audit) {
                healthRes.governor_audit.forEach((audit: Record<string, any>, i: number) => {
                    combined.push({
                        id: `gov_${i}`,
                        timestamp: audit.timestamp || new Date().toISOString(),
                        event_type: 'governor',
                        action: audit.action || 'audit',
                        severity: audit.approved === false ? 'error' : 'info',
                        summary: audit.reason || 'Governor audit check',
                        approved: audit.approved !== false
                    });
                });
            }

            // Sort by timestamp descending
            combined.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
            setEntries(combined);
        } catch (err) {
            console.error('Failed to fetch audit:', err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchAudit(); }, []);

    const severityIcon = (sev: string) => {
        switch (sev) {
            case 'critical': return <XCircle size={16} className="text-red-500" />;
            case 'error': return <AlertTriangle size={16} className="text-red-400" />;
            case 'warning': return <AlertTriangle size={16} className="text-yellow-400" />;
            default: return <Info size={16} className="text-blue-400" />;
        }
    };

    const severityColor = (sev: string) => {
        switch (sev) {
            case 'critical': return 'border-red-500/30 bg-red-500/5';
            case 'error': return 'border-red-400/20 bg-red-500/5';
            case 'warning': return 'border-yellow-400/20 bg-yellow-500/5';
            default: return 'border-border/40';
        }
    };

    const filtered = entries.filter(e => {
        if (filter !== 'all' && e.severity !== filter) return false;
        if (searchQuery && !e.summary.toLowerCase().includes(searchQuery.toLowerCase()) &&
            !e.action.toLowerCase().includes(searchQuery.toLowerCase())) return false;
        return true;
    });

    return (
        <div className="flex flex-col h-full w-full bg-background/50 relative overflow-hidden p-6 lg:p-10">
            <div className="absolute top-0 right-0 w-[600px] h-[400px] bg-red-500/5 rounded-full blur-[100px] pointer-events-none" />

            <header className="mb-6 flex flex-col md:flex-row md:items-center justify-between z-10 gap-4">
                <div>
                    <h2 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-red-400 to-rose-500 flex items-center gap-3">
                        <Shield className="text-red-400" /> 審計日誌
                    </h2>
                    <p className="text-muted-foreground mt-1 text-sm">{entries.length} 筆記錄</p>
                </div>
                <div className="flex items-center gap-3">
                    <div className="relative w-52">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                        <input type="text" placeholder="搜尋..." value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
                            className="w-full pl-9 pr-4 py-2 bg-secondary/30 border border-border/50 rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-red-500/50 text-foreground" />
                    </div>
                    <div className="flex items-center gap-1 bg-secondary/30 border border-border/50 rounded-lg p-1">
                        {['all', 'info', 'warning', 'error', 'critical'].map(f => (
                            <button key={f} onClick={() => setFilter(f)}
                                className={cn("px-2.5 py-1 rounded-md text-xs font-medium transition-all",
                                    filter === f ? "bg-primary/20 text-primary" : "text-muted-foreground hover:text-foreground"
                                )}>{f === 'all' ? '全部' : f}</button>
                        ))}
                    </div>
                    <button onClick={fetchAudit} className="p-2 text-muted-foreground hover:text-foreground bg-secondary/30 border border-border/50 rounded-lg transition-colors">
                        <RefreshCcw size={16} />
                    </button>
                </div>
            </header>

            <div className="flex-1 overflow-y-auto z-10 space-y-2 pr-2">
                {loading ? (
                    <div className="flex items-center justify-center h-40 text-muted-foreground">
                        <RefreshCcw size={24} className="animate-spin mr-3" /> 載入中...
                    </div>
                ) : filtered.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-40 text-muted-foreground border border-dashed border-border/50 rounded-xl">
                        <CheckCircle className="mb-2 opacity-50 text-emerald-400" size={32} />
                        <p className="text-sm">無審計記錄 — 系統運行正常</p>
                    </div>
                ) : (
                    filtered.map((entry, i) => (
                        <motion.div key={entry.id} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.02 }}
                            className={cn("glass-panel border rounded-xl p-4 transition-all", severityColor(entry.severity))}>
                            <div className="flex items-start gap-3">
                                <div className="mt-0.5">{severityIcon(entry.severity)}</div>
                                <div className="flex-1 min-w-0">
                                    <div className="flex items-center gap-2 mb-1">
                                        <span className="text-xs font-mono text-muted-foreground">{new Date(entry.timestamp).toLocaleString()}</span>
                                        <span className={cn("text-[10px] font-mono px-1.5 py-0.5 rounded",
                                            entry.event_type === 'governor' ? "bg-purple-500/20 text-purple-400" : "bg-orange-500/20 text-orange-400"
                                        )}>{entry.event_type}</span>
                                        <span className="text-xs font-medium text-foreground">{entry.action}</span>
                                        {entry.approved !== undefined && (
                                            <span className={cn("text-[10px] px-1.5 py-0.5 rounded",
                                                entry.approved ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"
                                            )}>{entry.approved ? 'APPROVED' : 'BLOCKED'}</span>
                                        )}
                                    </div>
                                    <p className="text-sm text-foreground/80">{entry.summary}</p>
                                    {entry.details && <p className="text-xs text-muted-foreground mt-1 font-mono bg-black/20 px-2 py-1 rounded">{entry.details}</p>}
                                </div>
                            </div>
                        </motion.div>
                    ))
                )}
            </div>
        </div>
    );
}
