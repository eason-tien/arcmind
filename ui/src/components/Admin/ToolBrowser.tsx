import { useEffect, useState } from 'react';
import { Cpu, RefreshCcw, Search, ChevronDown, ChevronUp, Copy, Check } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8100';

interface ToolSchema {
    name: string;
    description?: string;
    input_schema?: {
        type?: string;
        properties?: Record<string, { type: string; description?: string }>;
        required?: string[];
    };
    parameters?: {
        type: string;
        properties?: Record<string, { type: string; description?: string }>;
        required?: string[];
    };
}

export function ToolBrowser() {
    const [tools, setTools] = useState<ToolSchema[]>([]);
    const [loading, setLoading] = useState(true);
    const [searchQuery, setSearchQuery] = useState('');
    const [expandedTool, setExpandedTool] = useState<string | null>(null);
    const [copiedTool, setCopiedTool] = useState<string | null>(null);

    const fetchTools = async () => {
        try {
            setLoading(true);
            // Try /v1/tools first, then fall back to healthz
            let toolList: ToolSchema[] = [];
            try {
                const res = await fetch(`${API_BASE}/v1/tools`);
                if (res.ok) {
                    const data = await res.json();
                    toolList = data.tools || data || [];
                }
            } catch { /* fallback */ }

            if (toolList.length === 0) {
                const healthRes = await fetch(`${API_BASE}/healthz`);
                const health = await healthRes.json();
                if (health.tools) {
                    toolList = health.tools.map((name: string) => ({ name, description: '' }));
                }
            }
            setTools(toolList);
        } catch (err) {
            console.error('Failed to fetch tools:', err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchTools(); }, []);

    const copySchema = (tool: ToolSchema) => {
        navigator.clipboard.writeText(JSON.stringify(tool, null, 2));
        setCopiedTool(tool.name);
        setTimeout(() => setCopiedTool(null), 2000);
    };

    const filtered = tools.filter(t =>
        t.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (t.description || '').toLowerCase().includes(searchQuery.toLowerCase())
    );

    return (
        <div className="flex flex-col h-full w-full bg-background/50 relative overflow-hidden p-6 lg:p-10">
            <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[600px] h-[400px] bg-cyan-500/5 rounded-full blur-[100px] pointer-events-none" />

            <header className="mb-6 flex flex-col md:flex-row md:items-center justify-between z-10 gap-4">
                <div>
                    <h2 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-cyan-400 to-teal-500 flex items-center gap-3">
                        <Cpu className="text-cyan-400" /> Tool Registry
                    </h2>
                    <p className="text-muted-foreground mt-1 text-sm">{tools.length} 個已註冊工具</p>
                </div>
                <div className="flex items-center gap-3">
                    <div className="relative w-64">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                        <input type="text" placeholder="搜尋工具..." value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
                            className="w-full pl-9 pr-4 py-2 bg-secondary/30 border border-border/50 rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-cyan-500/50 text-foreground" />
                    </div>
                    <button onClick={fetchTools} className="p-2 text-muted-foreground hover:text-foreground bg-secondary/30 border border-border/50 rounded-lg transition-colors">
                        <RefreshCcw size={16} />
                    </button>
                </div>
            </header>

            <div className="flex-1 overflow-y-auto z-10 space-y-1.5 pr-2">
                {loading ? (
                    <div className="flex items-center justify-center h-40 text-muted-foreground">
                        <RefreshCcw size={24} className="animate-spin mr-3" /> 載入中...
                    </div>
                ) : (
                    filtered.map((tool, i) => {
                        const isExpanded = expandedTool === tool.name;
                        const schema = tool.input_schema || tool.parameters;
                        const paramCount = schema?.properties ? Object.keys(schema.properties).length : 0;

                        return (
                            <motion.div key={tool.name} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.01 }}
                                className="glass-panel border border-border/40 hover:border-cyan-500/30 rounded-xl transition-all">
                                <div className="flex items-center justify-between p-3 cursor-pointer" onClick={() => setExpandedTool(isExpanded ? null : tool.name)}>
                                    <div className="flex items-center gap-3 flex-1 min-w-0">
                                        <div className="p-1.5 rounded-lg bg-cyan-500/20 text-cyan-400 flex-shrink-0">
                                            <Cpu size={14} />
                                        </div>
                                        <span className="font-mono text-sm text-foreground">{tool.name}</span>
                                        {paramCount > 0 && (
                                            <span className="text-[10px] text-muted-foreground bg-secondary px-1.5 py-0.5 rounded">{paramCount} params</span>
                                        )}
                                    </div>
                                    <div className="flex items-center gap-2">
                                        <button onClick={(e) => { e.stopPropagation(); copySchema(tool); }}
                                            className="p-1 text-muted-foreground hover:text-foreground transition-colors" title="複製 Schema">
                                            {copiedTool === tool.name ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
                                        </button>
                                        {isExpanded ? <ChevronUp size={14} className="text-muted-foreground" /> : <ChevronDown size={14} className="text-muted-foreground" />}
                                    </div>
                                </div>
                                <AnimatePresence>
                                    {isExpanded && (
                                        <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                                            <div className="px-3 pb-3 border-t border-border/30 pt-2">
                                                {tool.description && <p className="text-xs text-muted-foreground mb-2">{tool.description}</p>}
                                                {schema?.properties && (
                                                    <div className="space-y-1">
                                                        <span className="text-[10px] font-semibold text-foreground/60 uppercase tracking-wider">Parameters</span>
                                                        {Object.entries(schema.properties).map(([key, val]) => (
                                                            <div key={key} className="flex items-start gap-2 text-xs font-mono bg-black/20 px-2 py-1.5 rounded">
                                                                <span className="text-cyan-400">{key}</span>
                                                                <span className="text-muted-foreground">: {val.type}</span>
                                                                {schema?.required?.includes(key) && <span className="text-red-400 text-[10px]">*</span>}
                                                                {val.description && <span className="text-muted-foreground/60 ml-2">— {val.description}</span>}
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}
                                            </div>
                                        </motion.div>
                                    )}
                                </AnimatePresence>
                            </motion.div>
                        );
                    })
                )}
            </div>
        </div>
    );
}
