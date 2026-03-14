import { useEffect, useState } from 'react';
import { Server, RefreshCcw, Activity, BrainCircuit, Database, ListTree, Network, Wrench, Shield, Cpu, HardDrive } from 'lucide-react';
import { motion } from 'framer-motion';
import { cn } from '../../lib/utils';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8100';

interface HealthData {
    status: string;
    version?: string;
    uptime?: number;
    lifecycle?: {
        active_agents: number;
        active_sessions: number;
        open_tasks: number;
    };
    skills_loaded?: number;
    tools_loaded?: number;
    ai_providers?: string[];
    mgis_online?: boolean;
    memory?: {
        working: number;
        short_term: number;
        long_term: number;
        vector: number;
    };
}

interface ModelData {
    default_model?: string;
    available_providers?: { provider: string; status: string }[];
    recommended_models?: Record<string, string[]>;
}

export function SystemStatus() {
    const [health, setHealth] = useState<HealthData | null>(null);
    const [models, setModels] = useState<ModelData | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

    const fetchAll = async () => {
        try {
            setLoading(true);
            const [healthRes, modelsRes] = await Promise.all([
                fetch(`${API_BASE}/healthz`).then(r => r.json()).catch(() => null),
                fetch(`${API_BASE}/v1/models`).then(r => r.json()).catch(() => null)
            ]);
            if (healthRes) setHealth(healthRes);
            if (modelsRes) setModels(modelsRes);
            setError('');
            setLastUpdate(new Date());
        } catch {
            setError('無法連接系統');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchAll();
        const interval = setInterval(fetchAll, 10000);
        return () => clearInterval(interval);
    }, []);

    const StatusBadge = ({ ok, label }: { ok: boolean; label: string }) => (
        <div className={cn(
            "flex items-center gap-2 px-3 py-2 rounded-lg border text-sm",
            ok
                ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
                : "bg-red-500/10 border-red-500/30 text-red-400"
        )}>
            <div className={cn("w-2 h-2 rounded-full", ok ? "bg-emerald-500 animate-pulse" : "bg-red-500")} />
            {label}
        </div>
    );

    const MetricCard = ({ icon: Icon, label, value, colorClass, sub }: {
        icon: typeof Activity; label: string; value: string | number; colorClass: string; sub?: string
    }) => (
        <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="bg-card/30 border border-border/40 p-4 rounded-xl flex items-center gap-4 transition-all hover:bg-card/50"
        >
            <div className={cn("p-3 rounded-lg flex-shrink-0", colorClass)}>
                <Icon size={22} />
            </div>
            <div className="flex flex-col">
                <span className="text-[11px] text-muted-foreground font-medium uppercase tracking-wider">{label}</span>
                <span className="text-xl font-semibold text-foreground mt-0.5">{loading && !health ? '...' : value}</span>
                {sub && <span className="text-[10px] text-muted-foreground">{sub}</span>}
            </div>
        </motion.div>
    );

    const providerCount = models?.available_providers?.length || health?.ai_providers?.length || 0;
    const modelCount = models?.recommended_models
        ? Object.values(models.recommended_models).reduce((sum, arr) => sum + arr.length, 0)
        : 0;

    return (
        <div className="flex flex-col h-full w-full bg-background/50 relative overflow-hidden p-6 lg:p-10">
            <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[800px] h-[400px] bg-blue-500/5 rounded-full blur-[120px] pointer-events-none" />

            <header className="mb-6 flex flex-col md:flex-row md:items-center justify-between z-10 gap-4">
                <div>
                    <h2 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-indigo-500 flex items-center gap-3">
                        <Server className="text-blue-400" />
                        系統總覽
                    </h2>
                    <p className="text-muted-foreground mt-1 text-sm">
                        即時系統狀態與指標
                        {lastUpdate && <span className="ml-2 font-mono text-xs">• 更新於 {lastUpdate.toLocaleTimeString()}</span>}
                    </p>
                </div>
                <button
                    onClick={fetchAll}
                    className="flex items-center gap-1.5 px-3 py-2 text-muted-foreground hover:text-foreground bg-secondary/30 border border-border/50 rounded-lg text-sm transition-colors"
                >
                    <RefreshCcw size={14} className={loading ? 'animate-spin' : ''} /> 重新整理
                </button>
            </header>

            <div className="flex-1 overflow-y-auto z-10 space-y-6 pr-2">
                {error && (
                    <div className="p-3 bg-red-500/10 border border-red-500/20 text-red-500 text-sm rounded-lg flex items-center gap-2">
                        <Activity size={16} /> {error}
                    </div>
                )}

                {/* Service Health */}
                <div>
                    <h3 className="text-sm font-semibold text-foreground/80 mb-3 uppercase tracking-wider">服務狀態</h3>
                    <div className="flex flex-wrap gap-3">
                        <StatusBadge ok={health?.status === 'ok'} label="ArcMind API" />
                        <StatusBadge ok={!!health?.mgis_online} label="MGIS Governance" />
                        <StatusBadge ok={providerCount > 0} label={`AI Providers (${providerCount})`} />
                        <StatusBadge ok={(health?.skills_loaded || 0) > 0} label={`Skills (${health?.skills_loaded || 0})`} />
                    </div>
                </div>

                {/* Core Metrics */}
                <div>
                    <h3 className="text-sm font-semibold text-foreground/80 mb-3 uppercase tracking-wider">核心指標</h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                        <MetricCard icon={BrainCircuit} label="活躍 Agent" value={health?.lifecycle?.active_agents || 0} colorClass="bg-purple-500/20 text-purple-400" />
                        <MetricCard icon={Activity} label="進行中 Session" value={health?.lifecycle?.active_sessions || 0} colorClass="bg-blue-500/20 text-blue-400" />
                        <MetricCard icon={ListTree} label="開放任務" value={health?.lifecycle?.open_tasks || 0} colorClass="bg-orange-500/20 text-orange-400" />
                        <MetricCard icon={Wrench} label="已載入技能" value={health?.skills_loaded || 0} colorClass="bg-emerald-500/20 text-emerald-400" />
                        <MetricCard icon={Cpu} label="已載入工具" value={health?.tools_loaded || 0} colorClass="bg-cyan-500/20 text-cyan-400" />
                        <MetricCard icon={Shield} label="Governor" value={health?.mgis_online ? '運作中' : '離線'} colorClass={health?.mgis_online ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"} />
                    </div>
                </div>

                {/* AI Providers */}
                {models?.available_providers && models.available_providers.length > 0 && (
                    <div>
                        <h3 className="text-sm font-semibold text-foreground/80 mb-3 uppercase tracking-wider">
                            AI Provider 狀態 ({providerCount} providers, {modelCount} models)
                        </h3>
                        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
                            {models.available_providers.map(p => (
                                <div key={p.provider} className="flex items-center gap-2 bg-card/30 border border-border/40 px-3 py-2.5 rounded-lg">
                                    <div className={cn(
                                        "w-2 h-2 rounded-full flex-shrink-0",
                                        p.status === 'ready' ? "bg-emerald-500" : "bg-yellow-500"
                                    )} />
                                    <span className="text-sm font-medium text-foreground truncate">{p.provider}</span>
                                    {models.recommended_models?.[p.provider] && (
                                        <span className="text-[10px] text-muted-foreground ml-auto flex-shrink-0">
                                            {models.recommended_models[p.provider].length} models
                                        </span>
                                    )}
                                </div>
                            ))}
                        </div>
                        {models.default_model && (
                            <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
                                <Network size={14} />
                                預設模型: <span className="font-mono text-primary">{models.default_model}</span>
                            </div>
                        )}
                    </div>
                )}

                {/* Memory Layers */}
                {health?.memory && (
                    <div>
                        <h3 className="text-sm font-semibold text-foreground/80 mb-3 uppercase tracking-wider">記憶層統計</h3>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                            {[
                                { label: 'Working', value: health.memory.working, color: 'bg-cyan-500' },
                                { label: 'Short-term', value: health.memory.short_term, color: 'bg-blue-500' },
                                { label: 'Long-term', value: health.memory.long_term, color: 'bg-purple-500' },
                                { label: 'Vector', value: health.memory.vector, color: 'bg-pink-500' },
                            ].map(m => (
                                <div key={m.label} className="bg-card/30 border border-border/40 p-3 rounded-xl text-center">
                                    <div className="text-xl font-bold text-foreground">{m.value}</div>
                                    <div className="text-[10px] text-muted-foreground uppercase tracking-wider mt-1">{m.label}</div>
                                    <div className="w-full h-1 bg-secondary rounded-full mt-2 overflow-hidden">
                                        <div className={cn("h-full rounded-full", m.color)} style={{ width: `${Math.min(100, m.value)}%` }} />
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* System Info */}
                <div>
                    <h3 className="text-sm font-semibold text-foreground/80 mb-3 uppercase tracking-wider">系統資訊</h3>
                    <div className="bg-card/30 border border-border/40 rounded-xl p-4 grid grid-cols-2 gap-y-2 text-sm">
                        <span className="text-muted-foreground flex items-center gap-2"><HardDrive size={14} /> 版本</span>
                        <span className="font-mono text-foreground">{health?.version || 'N/A'}</span>
                        <span className="text-muted-foreground flex items-center gap-2"><Activity size={14} /> Uptime</span>
                        <span className="font-mono text-foreground">
                            {health?.uptime ? `${Math.floor(health.uptime / 3600)}h ${Math.floor((health.uptime % 3600) / 60)}m` : 'N/A'}
                        </span>
                        <span className="text-muted-foreground flex items-center gap-2"><Database size={14} /> API Base</span>
                        <span className="font-mono text-foreground text-xs">{API_BASE}</span>
                    </div>
                </div>
            </div>
        </div>
    );
}
