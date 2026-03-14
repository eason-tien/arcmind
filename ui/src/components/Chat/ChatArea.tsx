import React from 'react';
import { Menu } from 'lucide-react';
import { useChatStore } from '../../store/chatStore';
import { MessageBubble } from './MessageBubble';
import { ChatInput } from './ChatInput';
import { VoiceOverlay } from './VoiceOverlay';
import { LiveFeed } from '../Dashboard/LiveFeed';
import { MemoryViewer } from '../Dashboard/MemoryViewer';
import { SkillManager } from '../Admin/SkillManager';
import { CronDashboard } from '../Admin/CronDashboard';
import { SystemStatus } from '../Admin/SystemStatus';
import { motion } from 'framer-motion';
import { useTranslation } from 'react-i18next';

export function ChatArea() {
    const { toggleSidebar, messages, activeSessionId, fetchMessages, activeTab } = useChatStore();
    const { t } = useTranslation();

    React.useEffect(() => {
        if (activeSessionId) {
            fetchMessages(activeSessionId);
        }
    }, [activeSessionId, fetchMessages]);

    return (
        <>
            <div className="flex flex-col h-full w-full bg-background/50 relative overflow-hidden">
                {activeTab === 'chat' && (
                    <>
                        {/* Background radial gradient for premium feel */}
                        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[800px] h-[400px] bg-primary/5 rounded-full blur-[120px] pointer-events-none" />

                        {/* Top Navbar */}
                        <header className="h-16 flex items-center justify-between px-4 lg:px-6 border-b border-border/40 glass z-20 titlebar-drag-region">
                            <div className="flex items-center gap-3 no-drag">
                                <button
                                    onClick={toggleSidebar}
                                    className="p-2 -ml-2 rounded-md hover:bg-secondary/50 text-muted-foreground transition-colors"
                                >
                                    <Menu size={20} />
                                </button>
                                <div className="flex flex-col select-text">
                                    <h1 className="text-sm font-semibold text-foreground tracking-wide">{t('sidebar.app_name', 'ArcMind')}</h1>
                                    <span className="text-xs text-primary/80">{t('chat.model_auto', 'Auto-routing')}</span>
                                </div>
                            </div>
                        </header>

                        {/* Messages Scroll Area */}
                        <div className="flex-1 overflow-y-auto px-4 lg:px-8 py-6 z-10 scroll-smooth">
                            <div className="max-w-3xl mx-auto flex flex-col gap-6 pb-20">

                                {messages.length === 0 ? (
                                    <motion.div
                                        initial={{ opacity: 0, y: 20 }}
                                        animate={{ opacity: 1, y: 0 }}
                                        className="flex flex-col items-center justify-center my-auto h-[50vh] text-center"
                                    >
                                        <div className="w-16 h-16 rounded-2xl bg-primary/10 flex items-center justify-center mb-6 shadow-[0_0_30px_rgba(139,92,246,0.2)] border border-primary/20">
                                            <span className="text-3xl">✨</span>
                                        </div>
                                        <h2 className="text-2xl font-bold text-foreground mb-2">{t('chat.welcome_title')}</h2>
                                        <p className="text-muted-foreground max-w-md">
                                            {t('chat.welcome_subtitle')}
                                        </p>
                                    </motion.div>
                                ) : (
                                    messages.map((msg, idx) => (
                                        <MessageBubble key={msg.id} message={msg} isLast={idx === messages.length - 1} />
                                    ))
                                )}

                            </div>
                        </div>

                        {/* Input Area */}
                        <div className="p-4 lg:px-8 bg-gradient-to-t from-background via-background to-transparent z-20 absolute bottom-0 w-full left-0">
                            <div className="max-w-3xl mx-auto">
                                <ChatInput />
                                <div className="text-center mt-3 text-[11px] text-muted-foreground/60">
                                    {t('chat.disclaimer', 'AI can make mistakes. Verify critical information.')}
                                </div>
                            </div>
                        </div>
                    </>
                )}

                {activeTab === 'dashboard' && <LiveFeed />}
                {activeTab === 'memory' && <MemoryViewer />}
                {activeTab === 'skills' && <SkillManager />}
                {activeTab === 'cron' && <CronDashboard />}
                {activeTab === 'system' && <SystemStatus />}

            </div>
            <VoiceOverlay />
        </>
    );
}
