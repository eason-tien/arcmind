import React, { useState, useRef, useEffect } from 'react';
import { Send, Paperclip, Mic } from 'lucide-react';
import { useChatStore } from '../../store/chatStore';
import { useTranslation } from 'react-i18next';

export function ChatInput() {
    const [input, setInput] = useState('');
    const { sendMessage, isGenerating, toggleVoiceMode } = useChatStore();
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const { t } = useTranslation();

    useEffect(() => {
        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto';
            textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 200) + 'px';
        }
    }, [input]);

    const handleSend = () => {
        if (!input.trim() || isGenerating) return;
        const text = input.trim();
        setInput('');
        sendMessage(text);
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    return (
        <div className="relative group">
            {/* Outer Glow */}
            <div className="absolute -inset-0.5 bg-gradient-to-r from-primary/30 to-purple-600/30 rounded-2xl blur opacity-30 group-focus-within:opacity-100 transition duration-500"></div>

            {/* Input Core */}
            <div className="relative flex items-end gap-2 bg-secondary/80 backdrop-blur-xl border border-border/80 rounded-2xl p-2 shadow-2xl">
                <button className="p-2.5 text-muted-foreground hover:text-foreground transition-colors rounded-xl hover:bg-background/50">
                    <Paperclip size={20} />
                </button>

                <textarea
                    ref={textareaRef}
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder={t('chat.input_placeholder')}
                    className="flex-1 max-h-[200px] min-h-[44px] bg-transparent border-none resize-none focus:outline-none focus:ring-0 px-2 py-3 text-foreground placeholder:text-muted-foreground/60 leading-relaxed text-[15px]"
                    rows={1}
                />

                {input.trim() ? (
                    <button
                        onClick={handleSend}
                        disabled={isGenerating}
                        className="p-2.5 bg-primary text-white rounded-xl hover:bg-primary-hover transition-all active:scale-95 disabled:opacity-50 disabled:active:scale-100 shadow-[0_0_15px_rgba(139,92,246,0.5)]"
                    >
                        <Send size={18} className={isGenerating ? "animate-pulse" : ""} />
                    </button>
                ) : (
                    <button
                        onClick={toggleVoiceMode}
                        className="p-2.5 text-muted-foreground hover:text-foreground transition-colors rounded-xl hover:bg-background/50"
                    >
                        <Mic size={20} />
                    </button>
                )}
            </div>
        </div>
    );
}
