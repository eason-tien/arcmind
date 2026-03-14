import { useState, createContext, useContext, useCallback } from 'react';
import type { ReactNode } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, CheckCircle, AlertTriangle, Info, XCircle } from 'lucide-react';
import { cn } from '../lib/utils';

interface Toast {
    id: string;
    type: 'success' | 'error' | 'warning' | 'info';
    title: string;
    message?: string;
    duration?: number;
}

interface NotificationContextType {
    addToast: (toast: Omit<Toast, 'id'>) => void;
}

const NotificationContext = createContext<NotificationContextType>({ addToast: () => {} });

export function useNotification() {
    return useContext(NotificationContext);
}

export function NotificationProvider({ children }: { children: ReactNode }) {
    const [toasts, setToasts] = useState<Toast[]>([]);

    const addToast = useCallback((toast: Omit<Toast, 'id'>) => {
        const id = `toast_${Date.now()}_${Math.random().toString(36).substring(2, 4)}`;
        setToasts(prev => [...prev, { ...toast, id }]);

        // Auto-dismiss
        setTimeout(() => {
            setToasts(prev => prev.filter(t => t.id !== id));
        }, toast.duration || 4000);
    }, []);

    const removeToast = (id: string) => {
        setToasts(prev => prev.filter(t => t.id !== id));
    };

    const iconMap = {
        success: <CheckCircle size={18} className="text-emerald-400" />,
        error: <XCircle size={18} className="text-red-400" />,
        warning: <AlertTriangle size={18} className="text-yellow-400" />,
        info: <Info size={18} className="text-blue-400" />,
    };

    const borderMap = {
        success: 'border-emerald-500/30',
        error: 'border-red-500/30',
        warning: 'border-yellow-500/30',
        info: 'border-blue-500/30',
    };

    return (
        <NotificationContext.Provider value={{ addToast }}>
            {children}
            {/* Toast Container */}
            <div className="fixed top-4 right-4 z-[100] flex flex-col gap-2 max-w-sm">
                <AnimatePresence mode="popLayout">
                    {toasts.map(toast => (
                        <motion.div
                            key={toast.id}
                            initial={{ opacity: 0, x: 50, scale: 0.95 }}
                            animate={{ opacity: 1, x: 0, scale: 1 }}
                            exit={{ opacity: 0, x: 50, scale: 0.95 }}
                            layout
                            className={cn(
                                "glass-panel border rounded-xl p-3 shadow-lg flex items-start gap-3 min-w-72",
                                borderMap[toast.type]
                            )}
                        >
                            <div className="mt-0.5 flex-shrink-0">{iconMap[toast.type]}</div>
                            <div className="flex-1 min-w-0">
                                <p className="text-sm font-medium text-foreground">{toast.title}</p>
                                {toast.message && <p className="text-xs text-muted-foreground mt-0.5">{toast.message}</p>}
                            </div>
                            <button onClick={() => removeToast(toast.id)} className="text-muted-foreground hover:text-foreground transition-colors flex-shrink-0">
                                <X size={14} />
                            </button>
                        </motion.div>
                    ))}
                </AnimatePresence>
            </div>
        </NotificationContext.Provider>
    );
}
