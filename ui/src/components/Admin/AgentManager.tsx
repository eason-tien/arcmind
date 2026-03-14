import { useEffect, useState } from 'react';
import { Bot, RefreshCcw, UserPlus, UserMinus, Crown, Shield } from 'lucide-react';
import { motion } from 'framer-motion';
import { cn } from '../../lib/utils';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8100';

interface Agent {
    id: string;
    name?: string;
    title?: string;
    model?: string;
    default_model?: string;
    role?: string;
    description?: string;
    status?: string;
    allowed_tools?: string[];
    capabilities?: string[];
    enabled?: boolean;
    is_core?: boolean;
}

export function AgentManager() {
    const [agents, setAgents] = useState<Agent[]>([]);
    const [loading, setLoading] = useState(true);

    const fetchAgents = async () => {
        try {
            setLoading(true);
            const res = await fetch(`${API_BASE}/healthz`);
            const health = await res.json();

            // Try dedicated agents endpoint, fall back to health data
            let agentList: Agent[] = [];
            try {
                const agentsRes = await fetch(`${API_BASE}/v1/agents`);
                if (agentsRes.ok) {
                    const data = await agentsRes.json();
                    agentList = data.agents || [];
                }
            } catch { /* fallback below */ }

            if (agentList.length === 0 && health.lifecycle?.registered_agents) {
                agentList = health.lifecycle.registered_agents;
            }

            // Default core agents if backend doesn't return list
            if (agentList.length === 0) {
                agentList = [
                    { id: 'ceo', title: 'CEO (執行長)', role: 'orchestrator', is_core: true, status: 'active' },
                    { id: 'search', title: '搜尋專員', role: 'search', is_core: true, status: 'active' },
                    { id: 'analysis', title: '數據分析師', role: 'analysis', is_core: true, status: 'active' },
                    { id: 'code', title: '軟體工程師', role: 'code', is_core: true, status: 'active' },
                    { id: 'qa', title: 'QA 工程師', role: 'qa', is_core: true, status: 'active' },
                    { id: 'devops', title: 'DevOps 工程師', role: 'devops', is_core: true, status: 'active' },
                    { id: 'pm', title: '產品經理', role: 'pm', is_core: true, status: 'active' },
                ];
            }
            setAgents(agentList);
        } catch (err) {
            console.error('Failed to fetch agents:', err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchAgents(); }, []);

    const coreAgents = agents.filter(a => a.is_core !== false);
    const hiredAgents = agents.filter(a => a.is_core === false);

    const AgentCard = ({ agent }: { agent: Agent }) => (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
            className="glass-panel border border-border/40 hover:border-purple-500/30 rounded-xl p-4 transition-all">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <div className={cn("p-2.5 rounded-lg",
                        agent.id === 'ceo' ? "bg-yellow-500/20 text-yellow-400" :
                        agent.is_core ? "bg-purple-500/20 text-purple-400" : "bg-cyan-500/20 text-cyan-400"
                    )}>
                        {agent.id === 'ceo' ? <Crown size={18} /> : <Bot size={18} />}
                    </div>
                    <div>
                        <div className="flex items-center gap-2">
                        <span className="font-medium text-foreground text-sm">{agent.name || agent.title || agent.id}</span>
                            {agent.is_core && (
                                <span className="text-[10px] font-mono bg-purple-500/20 text-purple-400 px-1.5 py-0.5 rounded">CORE</span>
                            )}
                        </div>
                        <div className="flex items-center gap-3 mt-1">
                            <span className="text-xs text-muted-foreground font-mono">{agent.id}</span>
                            {(agent.model || agent.default_model) && <span className="text-[10px] text-muted-foreground">{agent.model || agent.default_model}</span>}
                        </div>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <span className={cn("text-[10px] font-mono px-2 py-1 rounded-full",
                        agent.status === 'active' ? "bg-emerald-500/20 text-emerald-400" : "bg-gray-500/20 text-gray-400"
                    )}>{agent.status || 'active'}</span>
                    {!agent.is_core && (
                        <button className="p-1.5 text-red-400 hover:bg-red-500/20 rounded-lg transition-colors" title="解僱">
                            <UserMinus size={14} />
                        </button>
                    )}
                </div>
            </div>
            {agent.allowed_tools && agent.allowed_tools.length > 0 && agent.allowed_tools[0] !== '__all__' && (
                <div className="mt-3 flex flex-wrap gap-1">
                    {agent.allowed_tools.slice(0, 8).map(t => (
                        <span key={t} className="text-[10px] font-mono bg-secondary/50 text-muted-foreground px-1.5 py-0.5 rounded">{t}</span>
                    ))}
                    {agent.allowed_tools.length > 8 && (
                        <span className="text-[10px] text-muted-foreground">+{agent.allowed_tools.length - 8} more</span>
                    )}
                </div>
            )}
        </motion.div>
    );

    return (
        <div className="flex flex-col h-full w-full bg-background/50 relative overflow-hidden p-6 lg:p-10">
            <div className="absolute top-0 left-0 w-[600px] h-[400px] bg-purple-500/5 rounded-full blur-[100px] pointer-events-none" />

            <header className="mb-6 flex flex-col md:flex-row md:items-center justify-between z-10 gap-4">
                <div>
                    <h2 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-purple-400 to-violet-500 flex items-center gap-3">
                        <Bot className="text-purple-400" /> Agent 管理
                    </h2>
                    <p className="text-muted-foreground mt-1 text-sm">{agents.length} 位 Agent — {coreAgents.length} 核心 + {hiredAgents.length} 已聘用</p>
                </div>
                <div className="flex items-center gap-3">
                    <button className="flex items-center gap-1.5 px-3 py-2 bg-purple-500/20 text-purple-400 border border-purple-500/30 rounded-lg text-sm font-medium hover:bg-purple-500/30 transition-colors">
                        <UserPlus size={16} /> 聘用 Agent
                    </button>
                    <button onClick={fetchAgents} className="p-2 text-muted-foreground hover:text-foreground bg-secondary/30 border border-border/50 rounded-lg transition-colors">
                        <RefreshCcw size={16} />
                    </button>
                </div>
            </header>

            <div className="flex-1 overflow-y-auto z-10 space-y-6 pr-2">
                {loading ? (
                    <div className="flex items-center justify-center h-40 text-muted-foreground">
                        <RefreshCcw size={24} className="animate-spin mr-3" /> 載入中...
                    </div>
                ) : (
                    <>
                        <div>
                            <h3 className="text-xs font-semibold text-muted-foreground mb-3 uppercase tracking-wider flex items-center gap-2">
                                <Shield size={14} /> 核心員工 ({coreAgents.length})
                            </h3>
                            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                                {coreAgents.map(a => <AgentCard key={a.id} agent={a} />)}
                            </div>
                        </div>
                        {hiredAgents.length > 0 && (
                            <div>
                                <h3 className="text-xs font-semibold text-muted-foreground mb-3 uppercase tracking-wider flex items-center gap-2">
                                    <UserPlus size={14} /> 已聘用 ({hiredAgents.length})
                                </h3>
                                <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                                    {hiredAgents.map(a => <AgentCard key={a.id} agent={a} />)}
                                </div>
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    );
}
