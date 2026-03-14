import { useEffect, useState } from 'react';
import { Wrench, Search, ToggleLeft, ToggleRight, Play, ChevronDown, ChevronUp, RefreshCcw } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { cn } from '../../lib/utils';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8100';

interface Skill {
    name: string;
    description: string;
    version?: string;
    enabled?: boolean;
    category?: string;
    inputs?: Record<string, string>;
}

export function SkillManager() {
    const [skills, setSkills] = useState<Skill[]>([]);
    const [searchQuery, setSearchQuery] = useState('');
    const [loading, setLoading] = useState(true);
    const [expandedSkill, setExpandedSkill] = useState<string | null>(null);
    const [invokeResult, setInvokeResult] = useState<Record<string, string>>({});
    const [disabledSkills, setDisabledSkills] = useState<Set<string>>(new Set());

    const fetchSkills = async () => {
        try {
            setLoading(true);
            const res = await fetch(`${API_BASE}/v1/skills`);
            const data = await res.json();
            setSkills(data.skills || []);
        } catch (err) {
            console.error('Failed to fetch skills:', err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchSkills();
    }, []);

    const toggleSkill = (name: string) => {
        setDisabledSkills(prev => {
            const next = new Set(prev);
            if (next.has(name)) next.delete(name);
            else next.add(name);
            return next;
        });
    };

    const handleInvoke = async (skillName: string) => {
        try {
            setInvokeResult(prev => ({ ...prev, [skillName]: '⏳ Invoking...' }));
            const res = await fetch(`${API_BASE}/v1/skills/invoke`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ skill: skillName, inputs: {} })
            });
            const data = await res.json();
            setInvokeResult(prev => ({
                ...prev,
                [skillName]: res.ok ? JSON.stringify(data, null, 2) : `❌ ${data.detail || 'Error'}`
            }));
        } catch (err) {
            setInvokeResult(prev => ({ ...prev, [skillName]: '❌ Network error' }));
        }
    };

    const filtered = skills.filter(s =>
        s.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (s.description || '').toLowerCase().includes(searchQuery.toLowerCase())
    );

    const enabledCount = skills.length - disabledSkills.size;

    return (
        <div className="flex flex-col h-full w-full bg-background/50 relative overflow-hidden p-6 lg:p-10">
            <div className="absolute top-0 left-0 w-[600px] h-[400px] bg-emerald-500/5 rounded-full blur-[100px] pointer-events-none" />

            <header className="mb-6 flex flex-col md:flex-row md:items-center justify-between z-10 gap-4">
                <div>
                    <h2 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-emerald-400 to-teal-500 flex items-center gap-3">
                        <Wrench className="text-emerald-400" />
                        技能管理
                    </h2>
                    <p className="text-muted-foreground mt-1 text-sm">
                        管理所有已載入的 Skill — {enabledCount}/{skills.length} 已啟用
                    </p>
                </div>

                <div className="flex items-center gap-3">
                    <div className="relative w-64">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                        <input
                            type="text"
                            placeholder="搜尋技能..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            className="w-full pl-9 pr-4 py-2 bg-secondary/30 border border-border/50 rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-emerald-500/50 transition-all text-foreground"
                        />
                    </div>
                    <button
                        onClick={fetchSkills}
                        className="p-2 text-muted-foreground hover:text-foreground bg-secondary/30 border border-border/50 rounded-lg transition-colors"
                        title="重新載入"
                    >
                        <RefreshCcw size={16} />
                    </button>
                </div>
            </header>

            <div className="flex-1 overflow-y-auto z-10 space-y-2 pr-2 scroll-smooth">
                {loading ? (
                    <div className="flex items-center justify-center h-40 text-muted-foreground">
                        <RefreshCcw size={24} className="animate-spin mr-3" /> 載入中...
                    </div>
                ) : filtered.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-40 text-muted-foreground border border-dashed border-border/50 rounded-xl">
                        <Wrench className="mb-2 opacity-50" />
                        <p className="text-sm">未找到匹配的技能</p>
                    </div>
                ) : (
                    filtered.map((skill, i) => {
                        const isExpanded = expandedSkill === skill.name;
                        const isDisabled = disabledSkills.has(skill.name);

                        return (
                            <motion.div
                                initial={{ opacity: 0, y: 10 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={{ delay: i * 0.02 }}
                                key={skill.name}
                                className={cn(
                                    "glass-panel border rounded-xl transition-all",
                                    isDisabled
                                        ? "border-border/20 opacity-50"
                                        : "border-border/40 hover:border-emerald-500/30"
                                )}
                            >
                                <div
                                    className="flex items-center justify-between p-4 cursor-pointer"
                                    onClick={() => setExpandedSkill(isExpanded ? null : skill.name)}
                                >
                                    <div className="flex items-center gap-3 flex-1 min-w-0">
                                        <div className={cn(
                                            "p-2 rounded-lg flex-shrink-0",
                                            isDisabled ? "bg-gray-500/20 text-gray-500" : "bg-emerald-500/20 text-emerald-400"
                                        )}>
                                            <Wrench size={16} />
                                        </div>
                                        <div className="min-w-0">
                                            <div className="flex items-center gap-2">
                                                <span className="font-medium text-foreground text-sm">{skill.name}</span>
                                                {skill.version && (
                                                    <span className="text-[10px] font-mono text-muted-foreground bg-secondary px-1.5 py-0.5 rounded">
                                                        v{skill.version}
                                                    </span>
                                                )}
                                            </div>
                                            {skill.description && (
                                                <p className="text-xs text-muted-foreground mt-0.5 truncate">{skill.description}</p>
                                            )}
                                        </div>
                                    </div>

                                    <div className="flex items-center gap-3 flex-shrink-0">
                                        <button
                                            onClick={(e) => { e.stopPropagation(); toggleSkill(skill.name); }}
                                            className="transition-colors"
                                            title={isDisabled ? '啟用' : '停用'}
                                        >
                                            {isDisabled
                                                ? <ToggleLeft size={28} className="text-gray-500" />
                                                : <ToggleRight size={28} className="text-emerald-400" />
                                            }
                                        </button>
                                        {isExpanded ? <ChevronUp size={16} className="text-muted-foreground" /> : <ChevronDown size={16} className="text-muted-foreground" />}
                                    </div>
                                </div>

                                <AnimatePresence>
                                    {isExpanded && (
                                        <motion.div
                                            initial={{ height: 0, opacity: 0 }}
                                            animate={{ height: 'auto', opacity: 1 }}
                                            exit={{ height: 0, opacity: 0 }}
                                            className="overflow-hidden"
                                        >
                                            <div className="px-4 pb-4 border-t border-border/30 pt-3">
                                                <div className="flex items-center gap-2 mb-3">
                                                    <button
                                                        onClick={() => handleInvoke(skill.name)}
                                                        className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 rounded-lg text-xs font-medium hover:bg-emerald-500/30 transition-colors"
                                                    >
                                                        <Play size={12} /> 測試呼叫
                                                    </button>
                                                </div>
                                                {invokeResult[skill.name] && (
                                                    <pre className="text-xs font-mono bg-black/40 p-3 rounded-lg border border-white/5 text-muted-foreground whitespace-pre-wrap max-h-48 overflow-auto">
                                                        {invokeResult[skill.name]}
                                                    </pre>
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
