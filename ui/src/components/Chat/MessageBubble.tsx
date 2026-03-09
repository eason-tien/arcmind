import React from 'react';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { Copy, Check, User, Bot } from 'lucide-react';
import type { Message } from '../../store/chatStore';
import { motion } from 'framer-motion';
import { cn } from '../../lib/utils';

interface BubbleProps {
    message: Message;
    isLast: boolean;
}

export function MessageBubble({ message }: BubbleProps) {
    const isUser = message.role === 'user';
    const [copiedText, setCopiedText] = React.useState<string | null>(null);

    const copyToClipboard = (text: string) => {
        navigator.clipboard.writeText(text);
        setCopiedText(text);
        setTimeout(() => setCopiedText(null), 2000);
    };

    return (
        <motion.div
            initial={{ opacity: 0, y: 15 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, ease: 'easeOut' }}
            className={cn("flex w-full group", isUser ? "justify-end" : "justify-start")}
        >
            <div className={cn("flex max-w-[85%] gap-4", isUser ? "flex-row-reverse" : "flex-row")}>

                {/* Avatar */}
                <div className="flex-shrink-0 mt-1">
                    <div className={cn(
                        "w-8 h-8 rounded-lg flex items-center justify-center border",
                        isUser ? "bg-secondary text-foreground border-border" : "bg-primary/20 text-primary border-primary/30 shadow-[0_0_15px_rgba(139,92,246,0.15)]"
                    )}>
                        {isUser ? <User size={18} /> : <Bot size={18} />}
                    </div>
                </div>

                {/* Content Bubble */}
                <div className={cn(
                    "rounded-2xl px-5 py-3.5 prose prose-invert max-w-none text-[15px] leading-relaxed",
                    isUser
                        ? "bg-secondary text-foreground text-opacity-90 rounded-tr-sm border border-border/50"
                        : "bg-transparent text-foreground/90"
                )}>
                    {isUser ? (
                        <div className="whitespace-pre-wrap">{message.content}</div>
                    ) : (
                        <ReactMarkdown
                            components={{
                                code({ node, className, children, ...props }: any) {
                                    const match = /language-(\w+)/.exec(className || '');
                                    const isInline = !match && !String(children).includes('\n');

                                    if (isInline) {
                                        return (
                                            <code className="bg-secondary px-1.5 py-0.5 rounded-md text-[13px] border border-border font-mono text-primary-foreground" {...props}>
                                                {children}
                                            </code>
                                        );
                                    }

                                    const codeString = String(children).replace(/\n$/, '');
                                    return (
                                        <div className="relative group/code my-4 overflow-hidden rounded-xl border border-border bg-[#1E1E1E]">
                                            <div className="flex items-center justify-between px-4 py-2 bg-secondary/80 border-b border-border/50 text-xs text-muted-foreground font-mono">
                                                <span>{match?.[1] || 'text'}</span>
                                                <button
                                                    onClick={() => copyToClipboard(codeString)}
                                                    className="hover:text-foreground transition-colors flex items-center gap-1.5"
                                                >
                                                    {copiedText === codeString ? <Check size={14} className="text-green-400" /> : <Copy size={14} />}
                                                    {copiedText === codeString ? 'Copied' : 'Copy'}
                                                </button>
                                            </div>
                                            <div className="p-4 overflow-x-auto text-[13px]">
                                                <SyntaxHighlighter
                                                    style={vscDarkPlus as any}
                                                    language={match?.[1] || 'text'}
                                                    PreTag="div"
                                                    customStyle={{ margin: 0, padding: 0, background: 'transparent' }}
                                                    {...props}
                                                >
                                                    {codeString}
                                                </SyntaxHighlighter>
                                            </div>
                                        </div>
                                    );
                                }
                            }}
                        >
                            {message.content}
                        </ReactMarkdown>
                    )}
                </div>

            </div>
        </motion.div>
    );
}
