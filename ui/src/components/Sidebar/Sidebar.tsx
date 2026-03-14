import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { MessageSquare, Plus, Settings, BrainCircuit, X, Activity, Database, Wrench, Clock, Server, Trash2, Shield, Bot, Cpu, BarChart3, Globe, Sun, Moon } from 'lucide-react';
import { SettingsModal } from '../Settings/SettingsModal';
import { useChatStore } from '../../store/chatStore';
import { cn } from '../../lib/utils';
import { useTranslation } from 'react-i18next';
import { useTheme } from '../../lib/ThemeProvider';

export function Sidebar() {
    const { isSidebarOpen, toggleSidebar, sessions, activeSessionId, setActiveSession, fetchSessions, activeTab, setActiveTab, createSession, deleteSession } = useChatStore();
    const [isSettingsOpen, setIsSettingsOpen] = React.useState(false);
    const { t } = useTranslation();
    const { theme, toggleTheme } = useTheme();

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
                            <button
                                onClick={createSession}
                                className="w-full flex items-center justify-center gap-2 bg-primary/10 hover:bg-primary/20 text-primary border border-primary/20 rounded-xl py-2.5 transition-all active:scale-95 font-medium shadow-[0_0_15px_rgba(139,92,246,0.15)] hover:shadow-[0_0_20px_rgba(139,92,246,0.3)]"
                            >
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

                            <div className="text-xs font-medium text-muted-foreground mt-4 mb-2 px-2 uppercase tracking-wider">
                                管理
                            </div>

                            <button
                                onClick={() => setActiveTab('skills')}
                                className={cn(
                                    "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all text-left",
                                    activeTab === 'skills'
                                        ? "bg-emerald-500/15 text-emerald-400 font-medium"
                                        : "text-foreground/80 hover:bg-secondary/50"
                                )}
                            >
                                <Wrench size={16} className={activeTab === 'skills' ? "text-emerald-400" : "text-muted-foreground"} />
                                <span className="flex-1">技能管理</span>
                            </button>

                            <button
                                onClick={() => setActiveTab('cron')}
                                className={cn(
                                    "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all text-left",
                                    activeTab === 'cron'
                                        ? "bg-orange-500/15 text-orange-400 font-medium"
                                        : "text-foreground/80 hover:bg-secondary/50"
                                )}
                            >
                                <Clock size={16} className={activeTab === 'cron' ? "text-orange-400" : "text-muted-foreground"} />
                                <span className="flex-1">排程任務</span>
                            </button>

                            <button
                                onClick={() => setActiveTab('system')}
                                className={cn(
                                    "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all text-left",
                                    activeTab === 'system'
                                        ? "bg-blue-500/15 text-blue-400 font-medium"
                                        : "text-foreground/80 hover:bg-secondary/50"
                                )}
                            >
                                <Server size={16} className={activeTab === 'system' ? "text-blue-400" : "text-muted-foreground"} />
                                <span className="flex-1">系統總覽</span>
                            </button>

                            <button
                                onClick={() => setActiveTab('audit')}
                                className={cn(
                                    "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all text-left",
                                    activeTab === 'audit'
                                        ? "bg-red-500/15 text-red-400 font-medium"
                                        : "text-foreground/80 hover:bg-secondary/50"
                                )}
                            >
                                <Shield size={16} className={activeTab === 'audit' ? "text-red-400" : "text-muted-foreground"} />
                                <span className="flex-1">審計日誌</span>
                            </button>

                            <button
                                onClick={() => setActiveTab('agents')}
                                className={cn(
                                    "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all text-left",
                                    activeTab === 'agents'
                                        ? "bg-violet-500/15 text-violet-400 font-medium"
                                        : "text-foreground/80 hover:bg-secondary/50"
                                )}
                            >
                                <Bot size={16} className={activeTab === 'agents' ? "text-violet-400" : "text-muted-foreground"} />
                                <span className="flex-1">Agent 管理</span>
                            </button>

                            <button
                                onClick={() => setActiveTab('tools')}
                                className={cn(
                                    "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all text-left",
                                    activeTab === 'tools'
                                        ? "bg-cyan-500/15 text-cyan-400 font-medium"
                                        : "text-foreground/80 hover:bg-secondary/50"
                                )}
                            >
                                <Cpu size={16} className={activeTab === 'tools' ? "text-cyan-400" : "text-muted-foreground"} />
                                <span className="flex-1">工具註冊</span>
                            </button>

                            <button
                                onClick={() => setActiveTab('tokens')}
                                className={cn(
                                    "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all text-left",
                                    activeTab === 'tokens'
                                        ? "bg-amber-500/15 text-amber-400 font-medium"
                                        : "text-foreground/80 hover:bg-secondary/50"
                                )}
                            >
                                <BarChart3 size={16} className={activeTab === 'tokens' ? "text-amber-400" : "text-muted-foreground"} />
                                <span className="flex-1">Token 分析</span>
                            </button>

                            <button
                                onClick={() => setActiveTab('federation')}
                                className={cn(
                                    "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all text-left",
                                    activeTab === 'federation'
                                        ? "bg-indigo-500/15 text-indigo-400 font-medium"
                                        : "text-foreground/80 hover:bg-secondary/50"
                                )}
                            >
                                <Globe size={16} className={activeTab === 'federation' ? "text-indigo-400" : "text-muted-foreground"} />
                                <span className="flex-1">Federation</span>
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
                                <div
                                    key={session.id}
                                    className="group/session relative"
                                >
                                    <button
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
                                    <button
                                        onClick={(e) => { e.stopPropagation(); deleteSession(session.id); }}
                                        className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded-md text-muted-foreground hover:text-red-400 hover:bg-red-500/10 transition-all opacity-0 group-hover/session:opacity-100"
                                        title="刪除對話"
                                    >
                                        <Trash2 size={14} />
                                    </button>
                                </div>
                            ))}
                        </div>

                        {/* Footer Settings */}
                        <div className="p-4 border-t border-border/40 space-y-1">
                            <button
                                onClick={toggleTheme}
                                className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-foreground/80 hover:bg-secondary/50 transition-all"
                            >
                                {theme === 'dark' ? <Sun size={18} className="text-yellow-400" /> : <Moon size={18} className="text-blue-400" />}
                                <span>{theme === 'dark' ? '淺色模式' : '深色模式'}</span>
                            </button>
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
