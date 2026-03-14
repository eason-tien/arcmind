import { useEffect, useState } from 'react';
import { BarChart3, RefreshCcw, TrendingUp, DollarSign, Zap, Clock } from 'lucide-react';
import { motion } from 'framer-motion';
import { cn } from '../../lib/utils';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8100';

interface TokenStats {
    total_tokens: number;
    total_requests: number;
    by_provider: Record<string, { tokens: number; requests: number; cost_usd?: number }>;
    recent_sessions: { session_id: string; tokens: number; model?: string; elapsed_s?: number }[];
}

export function TokenAnalytics() {
    const [stats, setStats] = useState<TokenStats | null>(null);
    const [loading, setLoading] = useState(true);

    const fetchStats = async () => {
        try {
            setLoading(true);
            // Try dedicated analytics endpoint, fall back to aggregated health data
            let data: TokenStats | null = null;
            try {
                const res = await fetch(`${API_BASE}/v1/analytics/tokens`);
                if (res.ok) data = await res.json();
            } catch { /* fallback */ }

            if (!data) {
                // Build from health endpoint
                const healthRes = await fetch(`${API_BASE}/healthz`);
                const health = await healthRes.json();
                data = {
                    total_tokens: health.total_tokens || 0,
                    total_requests: health.total_requests || 0,
                    by_provider: health.token_by_provider || {},
                    recent_sessions: health.recent_token_usage || []
                };
            }
            setStats(data);
        } catch (err) {
            console.error('Failed to fetch token stats:', err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchStats(); }, []);

    const formatTokens = (n: number) => {
        if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
        if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
        return n.toString();
    };

    const totalCost = stats?.by_provider
        ? Object.values(stats.by_provider).reduce((sum, p) => sum + (p.cost_usd || 0), 0)
        : 0;

    const providers = stats?.by_provider ? Object.entries(stats.by_provider) : [];
    const maxProviderTokens = Math.max(...providers.map(([, v]) => v.tokens), 1);

    return (
        <div className="flex flex-col h-full w-full bg-background/50 relative overflow-hidden p-6 lg:p-10">
            <div className="absolute top-0 right-0 w-[600px] h-[400px] bg-amber-500/5 rounded-full blur-[100px] pointer-events-none" />

            <header className="mb-6 flex flex-col md:flex-row md:items-center justify-between z-10 gap-4">
                <div>
                    <h2 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-amber-400 to-yellow-500 flex items-center gap-3">
                        <BarChart3 className="text-amber-400" /> Token 分析
                    </h2>
                    <p className="text-muted-foreground mt-1 text-sm">API 用量與成本追蹤</p>
                </div>
                <button onClick={fetchStats} className="flex items-center gap-1.5 px-3 py-2 text-muted-foreground hover:text-foreground bg-secondary/30 border border-border/50 rounded-lg text-sm transition-colors">
                    <RefreshCcw size={14} className={loading ? 'animate-spin' : ''} /> 重新整理
                </button>
            </header>

            <div className="flex-1 overflow-y-auto z-10 space-y-6 pr-2">
                {/* Summary Cards */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    {[
                        { icon: Zap, label: '總 Tokens', value: formatTokens(stats?.total_tokens || 0), color: 'bg-amber-500/20 text-amber-400' },
                        { icon: TrendingUp, label: '總請求數', value: stats?.total_requests || 0, color: 'bg-blue-500/20 text-blue-400' },
                        { icon: DollarSign, label: '預估成本', value: `$${totalCost.toFixed(2)}`, color: 'bg-emerald-500/20 text-emerald-400' },
                        { icon: BarChart3, label: 'Provider 數', value: providers.length, color: 'bg-purple-500/20 text-purple-400' },
                    ].map(card => (
                        <motion.div key={card.label} initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }}
                            className="bg-card/30 border border-border/40 p-4 rounded-xl text-center">
                            <div className={cn("w-10 h-10 rounded-lg flex items-center justify-center mx-auto mb-2", card.color)}>
                                <card.icon size={20} />
                            </div>
                            <div className="text-xl font-bold text-foreground">{loading ? '...' : card.value}</div>
                            <div className="text-[10px] text-muted-foreground uppercase tracking-wider mt-1">{card.label}</div>
                        </motion.div>
                    ))}
                </div>

                {/* Provider Breakdown */}
                {providers.length > 0 && (
                    <div>
                        <h3 className="text-sm font-semibold text-foreground/80 mb-3 uppercase tracking-wider">各 Provider 用量</h3>
                        <div className="space-y-3">
                            {providers.map(([name, data]) => (
                                <div key={name} className="bg-card/30 border border-border/40 rounded-xl p-4">
                                    <div className="flex items-center justify-between mb-2">
                                        <span className="font-medium text-foreground text-sm">{name}</span>
                                        <div className="flex items-center gap-4 text-xs text-muted-foreground">
                                            <span>{formatTokens(data.tokens)} tokens</span>
                                            <span>{data.requests} requests</span>
                                            {data.cost_usd !== undefined && <span className="text-emerald-400">${data.cost_usd.toFixed(3)}</span>}
                                        </div>
                                    </div>
                                    <div className="w-full h-2 bg-secondary rounded-full overflow-hidden">
                                        <motion.div
                                            initial={{ width: 0 }} animate={{ width: `${(data.tokens / maxProviderTokens) * 100}%` }}
                                            transition={{ duration: 0.5, ease: 'easeOut' }}
                                            className="h-full bg-gradient-to-r from-amber-500 to-yellow-400 rounded-full"
                                        />
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* Recent Sessions */}
                {stats?.recent_sessions && stats.recent_sessions.length > 0 && (
                    <div>
                        <h3 className="text-sm font-semibold text-foreground/80 mb-3 uppercase tracking-wider">近期 Session 用量</h3>
                        <div className="bg-card/30 border border-border/40 rounded-xl overflow-hidden">
                            <div className="grid grid-cols-4 gap-4 px-4 py-2 bg-secondary/30 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider border-b border-border/40">
                                <span>Session</span><span>Model</span><span>Tokens</span><span>耗時</span>
                            </div>
                            {stats.recent_sessions.slice(0, 10).map((s, i) => (
                                <div key={i} className="grid grid-cols-4 gap-4 px-4 py-2.5 text-sm border-b border-border/20 last:border-0 hover:bg-secondary/20 transition-colors">
                                    <span className="font-mono text-xs text-foreground/80 truncate">{s.session_id}</span>
                                    <span className="text-xs text-muted-foreground">{s.model || '-'}</span>
                                    <span className="font-mono text-xs text-amber-400">{formatTokens(s.tokens)}</span>
                                    <span className="text-xs text-muted-foreground flex items-center gap-1">
                                        <Clock size={12} /> {s.elapsed_s ? `${s.elapsed_s.toFixed(1)}s` : '-'}
                                    </span>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {!loading && stats?.total_tokens === 0 && providers.length === 0 && (
                    <div className="flex flex-col items-center justify-center h-40 text-muted-foreground border border-dashed border-border/50 rounded-xl">
                        <BarChart3 className="mb-2 opacity-50" size={32} />
                        <p className="text-sm">尚無 Token 使用記錄</p>
                    </div>
                )}
            </div>
        </div>
    );
}
