import { useEffect, useState } from 'react';
import { Activity, Terminal, Code2, Globe, Bot } from 'lucide-react';
import { motion } from 'framer-motion';
import { useTranslation } from 'react-i18next';

interface LogEntry {
    id: string;
    timestamp: number;
    agent: string;
    action: string;
    details?: string;
    status: 'pending' | 'success' | 'error';
}

export function LiveFeed() {
    const { t } = useTranslation();
    const [logs, setLogs] = useState<LogEntry[]>([]);
    const [isConnected, setIsConnected] = useState(false);

    useEffect(() => {
        const ws = new WebSocket('ws://localhost:8100/ws/activity');

        ws.onopen = () => {
            setIsConnected(true);
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data) as LogEntry;
                setLogs(prevLogs => [data, ...prevLogs].slice(0, 100)); // Keep last 100 logs
            } catch (err) {
                console.error("Failed to parse activity WS message:", err);
            }
        };

        ws.onclose = () => {
            setIsConnected(false);
            // Simple reconnect logic
            setTimeout(() => {
                if (!isConnected) {
                    console.log("Attempting to reconnect LiveFeed WS...");
                    // A proper implementation would recreate the WebSocket
                    // For now, this is just a stub reconnect logic
                }
            }, 3000);
        };

        return () => {
            ws.close();
        };
    }, []);

    const getIcon = (action: string) => {
        if (action.includes('codebase')) return <Code2 size={16} />;
        if (action.includes('powershell') || action.includes('Terminal')) return <Terminal size={16} />;
        if (action.includes('search_web')) return <Globe size={16} />;
        return <Bot size={16} />;
    };

    return (
        <div className="flex flex-col h-full w-full bg-background/50 relative overflow-hidden p-6 lg:p-10">
            <div className="absolute top-0 right-0 w-[600px] h-[400px] bg-cyan-500/5 rounded-full blur-[100px] pointer-events-none" />

            <header className="mb-8 flex items-center justify-between z-10 titlebar-drag-region">
                <div>
                    <h2 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-cyan-400 to-blue-500 flex items-center gap-3">
                        <Activity className="text-cyan-400" />
                        {t('dashboard.live_title')}
                    </h2>
                    <p className="text-muted-foreground mt-1 text-sm">{t('dashboard.live_desc')}</p>
                </div>
                <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-secondary/50 border border-border/50 no-drag">
                    <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500 shadow-[0_0_10px_rgba(34,197,94,0.5)]' : 'bg-red-500'}`} />
                    <span className="text-xs font-mono">{isConnected ? 'WS CONNECTED' : 'DISCONNECTED'}</span>
                </div>
            </header>

            <div className="flex-1 overflow-y-auto glass-panel border border-border/40 rounded-xl p-4 z-10">
                <div className="space-y-4">
                    {logs.map((log) => (
                        <motion.div
                            initial={{ opacity: 0, x: -20 }}
                            animate={{ opacity: 1, x: 0 }}
                            key={log.id}
                            className="flex gap-4 p-4 rounded-lg bg-secondary/20 hover:bg-secondary/40 transition-colors border border-transparent hover:border-border/30"
                        >
                            <div className={`p-2 rounded-lg h-fit ${log.agent === 'ceo' ? 'bg-purple-500/20 text-purple-400' :
                                log.agent === 'windows_engineer' ? 'bg-blue-500/20 text-blue-400' :
                                    'bg-emerald-500/20 text-emerald-400'
                                }`}>
                                {getIcon(log.action)}
                            </div>
                            <div className="flex-1">
                                <div className="flex items-center justify-between mb-1">
                                    <div className="flex items-center gap-2">
                                        <span className="font-mono text-xs font-semibold uppercase tracking-wider text-foreground/80">{log.agent}</span>
                                        <span className="text-muted-foreground/50 text-xs">•</span>
                                        <span className="text-sm font-medium text-foreground">{log.action}</span>
                                    </div>
                                    <span className="text-xs font-mono text-muted-foreground">
                                        {new Date(log.timestamp).toLocaleTimeString()}
                                    </span>
                                </div>
                                {log.details && (
                                    <div className="text-sm text-muted-foreground font-mono bg-black/40 p-2 rounded border border-white/5 mt-2">
                                        &gt; {log.details}
                                        {log.status === 'pending' && <span className="ml-2 inline-block w-2 h-4 bg-cyan-400 animate-pulse align-middle" />}
                                    </div>
                                )}
                            </div>
                        </motion.div>
                    ))}
                    {logs.length === 0 && (
                        <div className="h-full flex flex-col items-center justify-center text-muted-foreground py-20">
                            <Activity size={48} className="mb-4 opacity-20" />
                            <p>{t('dashboard.no_activity')}</p>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
