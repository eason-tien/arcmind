import { useEffect, useState } from 'react';
import { Globe, RefreshCcw, Wifi, WifiOff } from 'lucide-react';
import { motion } from 'framer-motion';
import { cn } from '../../lib/utils';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8100';

interface PeerNode {
    instance_id: string;
    url: string;
    status: 'online' | 'offline' | 'syncing';
    last_seen?: string;
    role?: string;
    skills_count?: number;
    latency_ms?: number;
}

export function FederationDashboard() {
    const [peers, setPeers] = useState<PeerNode[]>([]);
    const [loading, setLoading] = useState(true);
    const [selfId, setSelfId] = useState('');

    const fetchFederation = async () => {
        try {
            setLoading(true);
            const res = await fetch(`${API_BASE}/healthz`);
            const health = await res.json();

            setSelfId(health.federation?.instance_id || 'local');

            let peerList: PeerNode[] = [];
            if (health.federation?.peers) {
                peerList = health.federation.peers;
            }

            // Try dedicated federation endpoint
            try {
                const fedRes = await fetch(`${API_BASE}/v1/federation/peers`);
                if (fedRes.ok) {
                    const data = await fedRes.json();
                    peerList = data.peers || peerList;
                }
            } catch { /* use health data */ }

            setPeers(peerList);
        } catch (err) {
            console.error('Failed to fetch federation:', err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchFederation(); }, []);

    const onlineCount = peers.filter(p => p.status === 'online').length;

    return (
        <div className="flex flex-col h-full w-full bg-background/50 relative overflow-hidden p-6 lg:p-10">
            <div className="absolute top-0 left-0 w-[600px] h-[400px] bg-indigo-500/5 rounded-full blur-[100px] pointer-events-none" />

            <header className="mb-6 flex flex-col md:flex-row md:items-center justify-between z-10 gap-4">
                <div>
                    <h2 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-indigo-400 to-blue-500 flex items-center gap-3">
                        <Globe className="text-indigo-400" /> Federation
                    </h2>
                    <p className="text-muted-foreground mt-1 text-sm">
                        本機: <span className="font-mono text-foreground">{selfId}</span> — {peers.length} 節點 ({onlineCount} 在線)
                    </p>
                </div>
                <button onClick={fetchFederation} className="flex items-center gap-1.5 px-3 py-2 text-muted-foreground hover:text-foreground bg-secondary/30 border border-border/50 rounded-lg text-sm transition-colors">
                    <RefreshCcw size={14} className={loading ? 'animate-spin' : ''} /> 重新整理
                </button>
            </header>

            <div className="flex-1 overflow-y-auto z-10 space-y-4 pr-2">
                {loading ? (
                    <div className="flex items-center justify-center h-40 text-muted-foreground">
                        <RefreshCcw size={24} className="animate-spin mr-3" /> 載入中...
                    </div>
                ) : peers.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-60 text-muted-foreground border border-dashed border-border/50 rounded-xl">
                        <Globe className="mb-3 opacity-30" size={48} />
                        <p className="text-sm mb-1">未啟用 Federation 或無已知節點</p>
                        <p className="text-xs text-muted-foreground/60">在 .env 設定 FEDERATION_ENABLED=true 以啟用</p>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {peers.map((peer, i) => (
                            <motion.div key={peer.instance_id} initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: i * 0.05 }}
                                className={cn("glass-panel border rounded-xl p-5 transition-all",
                                    peer.status === 'online' ? "border-emerald-500/30" : peer.status === 'syncing' ? "border-yellow-500/30" : "border-red-500/30 opacity-60"
                                )}>
                                <div className="flex items-center justify-between mb-3">
                                    <div className="flex items-center gap-3">
                                        <div className={cn("p-2.5 rounded-lg",
                                            peer.status === 'online' ? "bg-emerald-500/20 text-emerald-400" :
                                            peer.status === 'syncing' ? "bg-yellow-500/20 text-yellow-400" : "bg-red-500/20 text-red-400"
                                        )}>
                                            {peer.status === 'online' ? <Wifi size={18} /> : peer.status === 'syncing' ? <RefreshCcw size={18} className="animate-spin" /> : <WifiOff size={18} />}
                                        </div>
                                        <div>
                                            <div className="font-mono text-sm text-foreground">{peer.instance_id}</div>
                                            <div className="text-xs text-muted-foreground">{peer.url}</div>
                                        </div>
                                    </div>
                                    <span className={cn("text-[10px] font-mono px-2 py-1 rounded-full uppercase",
                                        peer.status === 'online' ? "bg-emerald-500/20 text-emerald-400" :
                                        peer.status === 'syncing' ? "bg-yellow-500/20 text-yellow-400" : "bg-red-500/20 text-red-400"
                                    )}>{peer.status}</span>
                                </div>
                                <div className="grid grid-cols-3 gap-4 text-xs">
                                    <div><span className="text-muted-foreground">角色</span><div className="font-medium text-foreground mt-0.5">{peer.role || 'worker'}</div></div>
                                    <div><span className="text-muted-foreground">Skills</span><div className="font-medium text-foreground mt-0.5">{peer.skills_count || '-'}</div></div>
                                    <div><span className="text-muted-foreground">延遲</span><div className="font-medium text-foreground mt-0.5">{peer.latency_ms ? `${peer.latency_ms}ms` : '-'}</div></div>
                                </div>
                                {peer.last_seen && (
                                    <div className="text-[10px] text-muted-foreground mt-2">最後通訊: {new Date(peer.last_seen).toLocaleString()}</div>
                                )}
                            </motion.div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}
