import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { MessageSquare, Plus, Settings, BrainCircuit, X, Activity, Database } from 'lucide-react';
import { SettingsModal } from '../Settings/SettingsModal';
import { useChatStore } from '../../store/chatStore';
import { cn } from '../../lib/utils';
import { useTranslation } from 'react-i18next';

export function Sidebar() {
    const { isSidebarOpen, toggleSidebar, sessions, activeSessionId, setActiveSession, fetchSessions, activeTab, setActiveTab } = useChatStore();
    const [isSettingsOpen, setIsSettingsOpen] = React.useState(false);
    const { t } = useTranslation();

    React.useEffect(() => {
        fetchSessions();
    }, [fetchSessions]);

    return (
        <>
            <AnimatePresence mode="wait" initial={false}>
                {isSidebarOpen && (
                    <motion.aside
                        initial={{ x: -300, opacity: 0 }}
                        animate={{ x: 0, opacity: 1 }}
                        exit={{ x: -300, opacity: 0 }}
                        transition={{ type: "spring", bounce: 0, duration: 0.4 }}
                        className="w-72 h-full glass-panel border-r border-border/50 flex flex-col fixed md:relative z-30"
                    >
                        {/* Header */}
                        <div className="h-16 flex items-center justify-between px-4 border-b border-border/40">
                            <div className="flex items-center gap-2 text-foreground font-semibold">
                                <div className="p-1.5 bg-primary/20 rounded-lg text-primary">
                                    <BrainCircuit size={20} />
                                </div>
                                <span className="tracking-wide">{t('sidebar.app_name')}</span>
                            </div>
                            <button
                                onClick={toggleSidebar}
                                className="md:hidden p-2 text-muted-foreground hover:text-foreground transition-colors"
                            >
                                <X size={20} />
                            </button>
                        </div>

                        {/* New Chat Button */}
                        <div className="p-4">
                            <button className="w-full flex items-center justify-center gap-2 bg-primary/10 hover:bg-primary/20 text-primary border border-primary/20 rounded-xl py-2.5 transition-all active:scale-95 font-medium shadow-[0_0_15px_rgba(139,92,246,0.15)] hover:shadow-[0_0_20px_rgba(139,92,246,0.3)]">
                                <Plus size={18} />
                                <span>{t('sidebar.new_chat')}</span>
                            </button>
                        </div>

                        {/* Navigation Tabs */}
                        <div className="px-3 pt-2 space-y-1">
                            <div className="text-xs font-medium text-muted-foreground mb-2 px-2 uppercase tracking-wider">
                                {t('sidebar.views', 'Views')}
                            </div>

                            <button
                                onClick={() => setActiveTab('chat')}
                                className={cn(
                                    "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all text-left",
                                    activeTab === 'chat'
                                        ? "bg-primary/15 text-primary font-medium"
                                        : "text-foreground/80 hover:bg-secondary/50"
                                )}
                            >
                                <MessageSquare size={16} className={activeTab === 'chat' ? "text-primary" : "text-muted-foreground"} />
                                <span className="flex-1">{t('sidebar.view_chat')}</span>
                            </button>

                            <button
                                onClick={() => setActiveTab('dashboard')}
                                className={cn(
                                    "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all text-left",
                                    activeTab === 'dashboard'
                                        ? "bg-primary/15 text-primary font-medium"
                                        : "text-foreground/80 hover:bg-secondary/50"
                                )}
                            >
                                <Activity size={16} className={activeTab === 'dashboard' ? "text-primary" : "text-muted-foreground"} />
                                <span className="flex-1">{t('sidebar.view_live')}</span>
                            </button>

                            <button
                                onClick={() => setActiveTab('memory')}
                                className={cn(
                                    "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all text-left",
                                    activeTab === 'memory'
                                        ? "bg-primary/15 text-primary font-medium"
                                        : "text-foreground/80 hover:bg-secondary/50"
                                )}
                            >
                                <Database size={16} className={activeTab === 'memory' ? "text-primary" : "text-muted-foreground"} />
                                <span className="flex-1">{t('sidebar.view_memory')}</span>
                            </button>
                        </div>

                        {/* Divider */}
                        <div className="mx-4 my-2 h-px bg-border/40" />

                        {/* Chat List */}
                        <div className="flex-1 overflow-y-auto px-3 space-y-1">
                            <div className="text-xs font-medium text-muted-foreground mb-3 px-2 uppercase tracking-wider">
                                {t('sidebar.recent')}
                            </div>
                            {sessions.map(session => (
                                <button
                                    key={session.id}
                                    onClick={() => setActiveSession(session.id)}
                                    className={cn(
                                        "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all text-left",
                                        activeSessionId === session.id
                                            ? "bg-primary/15 text-primary font-medium"
                                            : "text-foreground/80 hover:bg-secondary/50"
                                    )}
                                >
                                    <MessageSquare size={16} className={activeSessionId === session.id ? "text-primary" : "text-muted-foreground"} />
                                    <span className="truncate flex-1">{session.title}</span>
                                </button>
                            ))}
                        </div>

                        {/* Footer Settings */}
                        <div className="p-4 border-t border-border/40">
                            <button
                                onClick={() => setIsSettingsOpen(true)}
                                className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-foreground/80 hover:bg-secondary/50 transition-all"
                            >
                                <Settings size={18} className="text-muted-foreground" />
                                <span>{t('sidebar.settings')}</span>
                            </button>
                        </div>
                    </motion.aside>
                )}
            </AnimatePresence>
            <SettingsModal isOpen={isSettingsOpen} onClose={() => setIsSettingsOpen(false)} />
        </>
    );
}
