import { useState } from 'react';
import { Database, Network, Brain, Search, Terminal } from 'lucide-react';
import { motion } from 'framer-motion';
import { useTranslation } from 'react-i18next';

export function MemoryViewer() {
    const { t } = useTranslation();
    const [searchQuery, setSearchQuery] = useState('');

    // Mock data based on OpenClaw/ArcMind LTM architecture
    const memoryNodes = [
        { id: '1', type: 'semantic', concept: 'User Core Preference', value: 'Prefers Taiwan stock market simulations and automated GUI apps.', strength: 95 },
        { id: '2', type: 'episodic', concept: 'Recent Conversation', value: 'Discussed migrating ArcMind to a separate Windows 11 PC (192.168.1.151).', strength: 80 },
        { id: '3', type: 'semantic', concept: 'Architecture', value: 'Gateway running on macOS (8100), Worker running on Windows (8000).', strength: 90 },
        { id: '4', type: 'episodic', concept: 'Task History', value: 'Built Chaquopy Android hybrid app for OpenClaw.', strength: 75 },
    ];

    const filteredNodes = memoryNodes.filter(n =>
        n.concept.toLowerCase().includes(searchQuery.toLowerCase()) ||
        n.value.toLowerCase().includes(searchQuery.toLowerCase())
    );

    return (
        <div className="flex flex-col h-full w-full bg-background/50 relative overflow-hidden p-6 lg:p-10">
            {/* Background Glow */}
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] bg-purple-500/5 rounded-full blur-[150px] pointer-events-none" />

            {/* Header */}
            <header className="mb-8 flex flex-col md:flex-row md:items-center justify-between z-10 gap-4 titlebar-drag-region">
                <div>
                    <h2 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-purple-400 to-pink-500 flex items-center gap-3">
                        <Database className="text-purple-400" />
                        {t('dashboard.memory_title')}
                    </h2>
                    <p className="text-muted-foreground mt-1 text-sm">{t('dashboard.memory_desc')}</p>
                </div>

                <div className="relative w-full md:w-64 no-drag">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                    <input
                        type="text"
                        placeholder={t('dashboard.search_concepts') || "Search concepts..."}
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        className="w-full pl-9 pr-4 py-2 bg-secondary/30 border border-border/50 rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-purple-500/50 transition-all text-foreground"
                    />
                </div>
            </header>

            {/* Main Content Grid */}
            <div className="flex-1 grid grid-cols-1 lg:grid-cols-3 gap-6 z-10 overflow-hidden pb-4">

                {/* Left Panel: Nodes List */}
                <div className="lg:col-span-2 flex flex-col gap-4 overflow-y-auto pr-2 scroll-smooth">
                    {filteredNodes.map((node, i) => (
                        <motion.div
                            initial={{ opacity: 0, y: 20 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: i * 0.1 }}
                            key={node.id}
                            className="glass-panel border border-border/40 hover:border-purple-500/30 rounded-xl p-5 transition-all group cursor-pointer shadow-sm hover:shadow-[0_0_20px_rgba(168,85,247,0.1)]"
                        >
                            <div className="flex items-start justify-between mb-3">
                                <div className="flex items-center gap-2">
                                    <div className={`p-1.5 rounded-md ${node.type === 'semantic' ? 'bg-blue-500/20 text-blue-400' : 'bg-pink-500/20 text-pink-400'}`}>
                                        {node.type === 'semantic' ? <Brain size={14} /> : <Network size={14} />}
                                    </div>
                                    <span className="font-semibold text-foreground tracking-wide">{node.concept}</span>
                                </div>
                                <div className="flex items-center gap-2">
                                    <span className="text-xs font-mono text-muted-foreground">Strength: {node.strength}%</span>
                                    {/* Strength indicator bar */}
                                    <div className="w-16 h-1.5 bg-secondary rounded-full overflow-hidden">
                                        <div
                                            className={`h-full rounded-full ${node.type === 'semantic' ? 'bg-blue-400' : 'bg-pink-400'}`}
                                            style={{ width: `${node.strength}%` }}
                                        />
                                    </div>
                                </div>
                            </div>
                            <p className="text-sm text-foreground/80 leading-relaxed pl-8">
                                {node.value}
                            </p>
                        </motion.div>
                    ))}

                    {filteredNodes.length === 0 && (
                        <div className="flex flex-col items-center justify-center h-40 text-muted-foreground border border-dashed border-border/50 rounded-xl">
                            <Search className="mb-2 opacity-50" />
                            <p className="text-sm">No memory nodes found matching "{searchQuery}"</p>
                        </div>
                    )}
                </div>

                {/* Right Panel: Working Memory / Context Window */}
                <div className="hidden lg:flex flex-col glass-panel border border-border/40 rounded-xl overflow-hidden">
                    <div className="p-4 border-b border-border/40 bg-secondary/10 flex items-center justify-between">
                        <h3 className="font-medium text-sm text-foreground flex items-center gap-2">
                            <Terminal size={14} className="text-muted-foreground" />
                            {t('dashboard.active_context')}
                        </h3>
                        <span className="text-xs font-mono text-cyan-400 bg-cyan-400/10 px-2 py-0.5 rounded">8,192 / 128k</span>
                    </div>
                    <div className="flex-1 p-4 overflow-y-auto block bg-black/40 font-mono text-xs text-muted-foreground leading-relaxed whitespace-pre-wrap">
                        {`<system_prompt>
You are ArcMind CEO.
Current Time: 2026-03-08T23:30:00Z
</system_prompt>

<working_memory>
- User requested UI enhancements based on OpenClaw dashboard.
- Phase 7 plan approved.
- Currently modifying React UI src/ components.
</working_memory>

<retrieved_context>
Loading contextual memories...
[1] User prefers TailwindCSS...
[2] Gateway is available at http://localhost:8100/v1...
</retrieved_context>`}
                    </div>
                </div>

            </div>
        </div>
    );
}
