import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Activity, BrainCircuit, Database, ListTree, RefreshCcw, Network } from 'lucide-react';
import { cn } from '../../lib/utils';

export function SystemMonitor() {
    const { t } = useTranslation();
    const [stats, setStats] = useState<any>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    const fetchStats = async () => {
        try {
            const res = await fetch('/healthz');
            if (!res.ok) throw new Error('API Error');
            const data = await res.json();
            setStats(data);
            setError('');
        } catch (err) {
            console.error('Monitor fetch error:', err);
            setError('Connection failed');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchStats();
        // Poll every 5 seconds
        const interval = setInterval(fetchStats, 5000);
        return () => clearInterval(interval);
    }, []);

    const MetricCard = ({ icon: Icon, label, value, colorClass }: any) => (
        <div className="bg-card/30 border border-border/40 p-4 rounded-xl flex items-center gap-4 transition-all hover:bg-card/50">
            <div className={cn("p-3 rounded-lg flex-shrink-0", colorClass)}>
                <Icon size={24} />
            </div>
            <div className="flex flex-col">
                <span className="text-xs text-muted-foreground font-medium uppercase tracking-wider">{label}</span>
                <span className="text-xl font-semibold text-foreground mt-0.5">
                    {loading && !stats ? '...' : value}
                </span>
            </div>
        </div>
    );

    return (
        <div className="space-y-6 animate-in fade-in duration-300">
            <div className="flex items-center justify-between">
                <div>
                    <h3 className="text-lg font-semibold text-foreground">{t('monitor.title')}</h3>
                    <p className="text-sm text-muted-foreground mt-1">{t('monitor.desc')}</p>
                </div>
                {/* Status Indicator */}
                <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-secondary/50 border border-border/50">
                    <div className={cn("w-2 h-2 rounded-full animate-pulse", error ? "bg-red-500" : "bg-green-500")} />
                    <span className="text-xs font-medium text-foreground/80">
                        {error ? t('monitor.status_offline') : t('monitor.status_online')}
                    </span>
                </div>
            </div>

            {error && (
                <div className="p-3 bg-red-500/10 border border-red-500/20 text-red-500 text-sm rounded-lg flex items-center gap-2">
                    <Activity size={16} />
                    {error}
                </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <MetricCard
                    icon={BrainCircuit}
                    label={t('monitor.metric_agents')}
                    value={stats?.lifecycle?.active_agents || 0}
                    colorClass="bg-purple-500/20 text-purple-400"
                />
                <MetricCard
                    icon={Activity}
                    label={t('monitor.metric_sessions')}
                    value={stats?.lifecycle?.active_sessions || 0}
                    colorClass="bg-blue-500/20 text-blue-400"
                />
                <MetricCard
                    icon={ListTree}
                    label={t('monitor.metric_tasks')}
                    value={stats?.lifecycle?.open_tasks || 0}
                    colorClass="bg-orange-500/20 text-orange-400"
                />
                <MetricCard
                    icon={Database}
                    label={t('monitor.mgis_database')}
                    value={stats?.mgis_online ? 'Connected' : 'Disconnected'}
                    colorClass={stats?.mgis_online ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"}
                />
                <MetricCard
                    icon={Network}
                    label={t('monitor.metric_providers')}
                    value={stats?.ai_providers?.length || 0}
                    colorClass="bg-cyan-500/20 text-cyan-400"
                />
                <MetricCard
                    icon={RefreshCcw}
                    label={t('monitor.metric_skills')}
                    value={stats?.skills_loaded || 0}
                    colorClass="bg-pink-500/20 text-pink-400"
                />
            </div>
        </div>
    );
}
