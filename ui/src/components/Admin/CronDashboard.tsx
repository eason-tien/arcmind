import { useEffect, useState } from 'react';
import { Clock, Plus, Trash2, Play, Pause, RotateCcw, RefreshCcw, AlertCircle } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { cn } from '../../lib/utils';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8100';

interface CronJob {
    name: string;
    cron_expression: string;
    command: string;
    timezone?: string;
    status?: string;
    next_run?: string;
    last_run?: string;
}

export function CronDashboard() {
    const [jobs, setJobs] = useState<CronJob[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [showCreate, setShowCreate] = useState(false);
    const [newJob, setNewJob] = useState({ name: '', cron_expression: '', command: '', timezone: 'Asia/Taipei' });
    const [actionFeedback, setActionFeedback] = useState<Record<string, string>>({});

    const fetchJobs = async () => {
        try {
            setLoading(true);
            const res = await fetch(`${API_BASE}/v1/cron/`);
            const data = await res.json();
            setJobs(data.jobs || data || []);
            setError('');
        } catch (err) {
            setError('無法連接排程服務');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchJobs(); }, []);

    const handleAction = async (name: string, action: 'trigger' | 'pause' | 'resume' | 'delete') => {
        try {
            const method = action === 'delete' ? 'DELETE' : 'POST';
            const url = action === 'delete'
                ? `${API_BASE}/v1/cron/${name}`
                : `${API_BASE}/v1/cron/${name}/${action}`;

            const res = await fetch(url, { method });
            if (res.ok) {
                setActionFeedback(prev => ({ ...prev, [name]: `✅ ${action} 成功` }));
                setTimeout(() => setActionFeedback(prev => { const n = { ...prev }; delete n[name]; return n; }), 2000);
                fetchJobs();
            } else {
                const data = await res.json();
                setActionFeedback(prev => ({ ...prev, [name]: `❌ ${data.detail || 'Error'}` }));
            }
        } catch {
            setActionFeedback(prev => ({ ...prev, [name]: '❌ 網路錯誤' }));
        }
    };

    const handleCreate = async () => {
        try {
            const res = await fetch(`${API_BASE}/v1/cron/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(newJob)
            });
            if (res.ok) {
                setShowCreate(false);
                setNewJob({ name: '', cron_expression: '', command: '', timezone: 'Asia/Taipei' });
                fetchJobs();
            }
        } catch (err) {
            console.error('Failed to create cron job:', err);
        }
    };

    return (
        <div className="flex flex-col h-full w-full bg-background/50 relative overflow-hidden p-6 lg:p-10">
            <div className="absolute top-0 right-0 w-[600px] h-[400px] bg-orange-500/5 rounded-full blur-[100px] pointer-events-none" />

            <header className="mb-6 flex flex-col md:flex-row md:items-center justify-between z-10 gap-4">
                <div>
                    <h2 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-orange-400 to-amber-500 flex items-center gap-3">
                        <Clock className="text-orange-400" />
                        排程任務管理
                    </h2>
                    <p className="text-muted-foreground mt-1 text-sm">
                        管理 Cron 排程 — {jobs.length} 個任務
                    </p>
                </div>
                <div className="flex items-center gap-3">
                    <button
                        onClick={() => setShowCreate(!showCreate)}
                        className="flex items-center gap-1.5 px-3 py-2 bg-orange-500/20 text-orange-400 border border-orange-500/30 rounded-lg text-sm font-medium hover:bg-orange-500/30 transition-colors"
                    >
                        <Plus size={16} /> 新增排程
                    </button>
                    <button
                        onClick={fetchJobs}
                        className="p-2 text-muted-foreground hover:text-foreground bg-secondary/30 border border-border/50 rounded-lg transition-colors"
                    >
                        <RefreshCcw size={16} />
                    </button>
                </div>
            </header>

            {/* Create Form */}
            <AnimatePresence>
                {showCreate && (
                    <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        className="overflow-hidden z-10 mb-4"
                    >
                        <div className="glass-panel border border-orange-500/30 rounded-xl p-5 space-y-3">
                            <h3 className="text-sm font-semibold text-foreground">建立新排程</h3>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                <input
                                    placeholder="任務名稱 (e.g. daily_report)"
                                    value={newJob.name}
                                    onChange={e => setNewJob(prev => ({ ...prev, name: e.target.value }))}
                                    className="bg-secondary/30 border border-border/50 rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-orange-500/50"
                                />
                                <input
                                    placeholder="Cron 表達式 (e.g. 0 21 * * *)"
                                    value={newJob.cron_expression}
                                    onChange={e => setNewJob(prev => ({ ...prev, cron_expression: e.target.value }))}
                                    className="bg-secondary/30 border border-border/50 rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-orange-500/50 font-mono"
                                />
                            </div>
                            <textarea
                                placeholder="執行指令 (e.g. Generate daily summary report)"
                                value={newJob.command}
                                onChange={e => setNewJob(prev => ({ ...prev, command: e.target.value }))}
                                className="w-full bg-secondary/30 border border-border/50 rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-orange-500/50 resize-none"
                                rows={2}
                            />
                            <div className="flex justify-end gap-2">
                                <button onClick={() => setShowCreate(false)} className="px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors">取消</button>
                                <button
                                    onClick={handleCreate}
                                    disabled={!newJob.name || !newJob.cron_expression || !newJob.command}
                                    className="px-4 py-1.5 bg-orange-500/20 text-orange-400 border border-orange-500/30 rounded-lg text-sm font-medium hover:bg-orange-500/30 transition-colors disabled:opacity-40"
                                >
                                    建立
                                </button>
                            </div>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>

            {error && (
                <div className="p-3 bg-red-500/10 border border-red-500/20 text-red-500 text-sm rounded-lg flex items-center gap-2 mb-4 z-10">
                    <AlertCircle size={16} /> {error}
                </div>
            )}

            <div className="flex-1 overflow-y-auto z-10 space-y-2 pr-2">
                {loading ? (
                    <div className="flex items-center justify-center h-40 text-muted-foreground">
                        <RefreshCcw size={24} className="animate-spin mr-3" /> 載入中...
                    </div>
                ) : jobs.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-40 text-muted-foreground border border-dashed border-border/50 rounded-xl">
                        <Clock className="mb-2 opacity-50" />
                        <p className="text-sm">尚無排程任務</p>
                    </div>
                ) : (
                    jobs.map((job, i) => (
                        <motion.div
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: i * 0.03 }}
                            key={job.name}
                            className="glass-panel border border-border/40 hover:border-orange-500/30 rounded-xl p-4 transition-all"
                        >
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-3">
                                    <div className={cn(
                                        "p-2 rounded-lg",
                                        job.status === 'paused' ? "bg-yellow-500/20 text-yellow-400" : "bg-orange-500/20 text-orange-400"
                                    )}>
                                        <Clock size={16} />
                                    </div>
                                    <div>
                                        <div className="flex items-center gap-2">
                                            <span className="font-medium text-foreground text-sm">{job.name}</span>
                                            <span className={cn(
                                                "text-[10px] font-mono px-1.5 py-0.5 rounded",
                                                job.status === 'paused'
                                                    ? "bg-yellow-500/20 text-yellow-400"
                                                    : "bg-emerald-500/20 text-emerald-400"
                                            )}>
                                                {job.status || 'active'}
                                            </span>
                                        </div>
                                        <div className="flex items-center gap-4 mt-1">
                                            <span className="text-xs font-mono text-muted-foreground">{job.cron_expression}</span>
                                            <span className="text-xs text-muted-foreground truncate max-w-xs">{job.command}</span>
                                        </div>
                                    </div>
                                </div>

                                <div className="flex items-center gap-1.5">
                                    {actionFeedback[job.name] && (
                                        <span className="text-xs mr-2">{actionFeedback[job.name]}</span>
                                    )}
                                    <button
                                        onClick={() => handleAction(job.name, 'trigger')}
                                        className="p-1.5 text-cyan-400 hover:bg-cyan-500/20 rounded-lg transition-colors"
                                        title="立即觸發"
                                    >
                                        <Play size={14} />
                                    </button>
                                    <button
                                        onClick={() => handleAction(job.name, job.status === 'paused' ? 'resume' : 'pause')}
                                        className="p-1.5 text-yellow-400 hover:bg-yellow-500/20 rounded-lg transition-colors"
                                        title={job.status === 'paused' ? '恢復' : '暫停'}
                                    >
                                        {job.status === 'paused' ? <RotateCcw size={14} /> : <Pause size={14} />}
                                    </button>
                                    <button
                                        onClick={() => handleAction(job.name, 'delete')}
                                        className="p-1.5 text-red-400 hover:bg-red-500/20 rounded-lg transition-colors"
                                        title="刪除"
                                    >
                                        <Trash2 size={14} />
                                    </button>
                                </div>
                            </div>
                        </motion.div>
                    ))
                )}
            </div>
        </div>
    );
}
