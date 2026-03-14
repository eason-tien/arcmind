import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Server, Key, Eye, EyeOff, CheckCircle2 } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useTranslation } from 'react-i18next';
import { SystemMonitor } from './SystemMonitor';

interface SettingsModalProps {
    isOpen: boolean;
    onClose: () => void;
}

export function SettingsModal({ isOpen, onClose }: SettingsModalProps) {
    const [activeTab, setActiveTab] = useState<'models' | 'system' | 'monitor'>('models');
    const [providers, setProviders] = useState<{ provider: string, status: string }[]>([]);
    const [recommended, setRecommended] = useState<Record<string, string[]>>({});
    const [selectedModel, setSelectedModel] = useState<string>('');
    const [isCustomModel, setIsCustomModel] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const { t, i18n } = useTranslation();

    const [apiKeys, setApiKeys] = useState<Record<string, string>>({});
    const [showKey, setShowKey] = useState<Record<string, boolean>>({});

    useEffect(() => {
        if (isOpen) {
            // Fetch available models from backend
            fetch('/v1/models')
                .then(res => res.json())
                .then(data => {
                    setProviders(data.available_providers || []);
                    const rec = data.recommended_models || {};
                    setRecommended(rec);
                    if (data.default_model) {
                        setSelectedModel(data.default_model);
                        const allRecs = Object.values(rec).flat();
                        if (!allRecs.includes(data.default_model)) {
                            setIsCustomModel(true);
                        }
                    }
                })
                .catch(err => console.error("Failed to fetch models:", err));
        }
    }, [isOpen]);

    const handleKeyChange = (provider: string, val: string) => {
        setApiKeys(prev => ({ ...prev, [provider]: val }));
    };

    const toggleKeyVision = (provider: string) => {
        setShowKey(prev => ({ ...prev, [provider]: !prev[provider] }));
    };

    const handleLanguageChange = (lng: string) => {
        i18n.changeLanguage(lng);
    };

    const handleSave = async () => {
        setIsSaving(true);
        try {
            await fetch('/v1/models/default', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model: selectedModel })
            });
            onClose();
        } catch (err) {
            console.error(err);
        } finally {
            setIsSaving(false);
        }
    };

    return (
        <AnimatePresence>
            {isOpen && (
                <>
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        onClick={onClose}
                        className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
                    />
                    <motion.div
                        initial={{ opacity: 0, scale: 0.95, y: 20 }}
                        animate={{ opacity: 1, scale: 1, y: 0 }}
                        exit={{ opacity: 0, scale: 0.95, y: 20 }}
                        transition={{ type: "spring", bounce: 0, duration: 0.4 }}
                        className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-2xl max-h-[85vh] flex flex-col glass-panel rounded-2xl border border-border/50 shadow-2xl overflow-hidden"
                    >
                        {/* Header */}
                        <div className="flex items-center justify-between px-6 py-4 border-b border-border/40">
                            <h2 className="text-lg font-semibold text-foreground flex items-center gap-2">
                                <Server size={20} className="text-primary" />
                                {t('settings.title')}
                            </h2>
                            <button
                                onClick={onClose}
                                className="p-1.5 text-muted-foreground hover:text-foreground hover:bg-secondary/50 rounded-lg transition-colors"
                            >
                                <X size={20} />
                            </button>
                        </div>

                        {/* Content Container */}
                        <div className="flex flex-1 overflow-hidden">

                            {/* Sidebar Tabs */}
                            <div className="w-48 border-r border-border/40 bg-card/30 p-4 space-y-1">
                                <button
                                    onClick={() => setActiveTab('models')}
                                    className={cn(
                                        "w-full text-left px-3 py-2 rounded-lg text-sm transition-all",
                                        activeTab === 'models' ? "bg-primary/20 text-primary font-medium" : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground"
                                    )}
                                >
                                    {t('settings.tab_models')}
                                </button>
                                <button
                                    onClick={() => setActiveTab('system')}
                                    className={cn(
                                        "w-full text-left px-3 py-2 rounded-lg text-sm transition-all",
                                        activeTab === 'system' ? "bg-primary/20 text-primary font-medium" : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground"
                                    )}
                                >
                                    {t('settings.tab_system')}
                                </button>
                                <button
                                    onClick={() => setActiveTab('monitor')}
                                    className={cn(
                                        "w-full text-left px-3 py-2 rounded-lg text-sm transition-all",
                                        activeTab === 'monitor' ? "bg-primary/20 text-primary font-medium" : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground"
                                    )}
                                >
                                    {t('settings.tab_monitor')}
                                </button>
                            </div>

                            {/* Main Tab Content */}
                            <div className="flex-1 overflow-y-auto p-6 scroll-smooth">
                                {activeTab === 'models' && (
                                    <div className="space-y-8 animate-in fade-in duration-300">

                                        {/* Default Model Selector */}
                                        <div className="space-y-3">
                                            <h3 className="text-sm font-medium text-foreground">{t('settings.global_model_title')}</h3>
                                            <p className="text-xs text-muted-foreground">{t('settings.global_model_desc')}</p>
                                            <div className="flex flex-col gap-2">
                                                <select
                                                    value={isCustomModel ? "__custom__" : selectedModel}
                                                    onChange={(e) => {
                                                        if (e.target.value === "__custom__") {
                                                            setIsCustomModel(true);
                                                        } else {
                                                            setIsCustomModel(false);
                                                            setSelectedModel(e.target.value);
                                                        }
                                                    }}
                                                    className="w-full bg-secondary text-foreground border border-border rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-primary/50 outline-none transition-all appearance-none cursor-pointer"
                                                >
                                                    {Object.entries(recommended).map(([providerName, models]) => (
                                                        <optgroup key={providerName} label={providerName.toUpperCase()}>
                                                            {models.map(m => (
                                                                <option key={m} value={m}>{m}</option>
                                                            ))}
                                                        </optgroup>
                                                    ))}
                                                    <option value="__custom__">Other (Custom Input)...</option>
                                                </select>

                                                {isCustomModel && (
                                                    <input
                                                        type="text"
                                                        value={selectedModel}
                                                        onChange={(e) => setSelectedModel(e.target.value)}
                                                        placeholder="custom_provider:model-name (e.g. ollama:qwen3)"
                                                        className="w-full bg-background text-foreground border border-border rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-primary/50 outline-none transition-all mt-1"
                                                        autoFocus
                                                    />
                                                )}
                                            </div>
                                        </div>

                                        <hr className="border-border/40" />

                                        {/* API Keys Configuration */}
                                        <div className="space-y-4">
                                            <div>
                                                <h3 className="text-sm font-medium text-foreground">{t('settings.api_keys_title')}</h3>
                                                <p className="text-xs text-muted-foreground mt-1">{t('settings.api_keys_desc')}</p>
                                            </div>

                                            {(() => {
                                                const activeProvider = selectedModel ? selectedModel.split(':')[0] : 'openai';
                                                return (
                                                    <div key={activeProvider} className="flex flex-col gap-2 p-3 rounded-xl border border-border/40 bg-card/20">
                                                        <label className="text-xs font-semibold text-foreground/80 uppercase tracking-wider flex items-center justify-between">
                                                            {activeProvider}
                                                            {providers.some(p => p.provider === activeProvider) && (
                                                                <span className="flex items-center gap-1 text-[10px] text-green-400 normal-case tracking-normal">
                                                                    <CheckCircle2 size={12} /> {t('settings.registered')}
                                                                </span>
                                                            )}
                                                        </label>
                                                        <div className="relative flex items-center">
                                                            <Key size={16} className="absolute left-3 text-muted-foreground" />
                                                            <input
                                                                type={showKey[activeProvider] ? 'text' : 'password'}
                                                                value={apiKeys[activeProvider] || ''}
                                                                onChange={(e) => handleKeyChange(activeProvider, e.target.value)}
                                                                placeholder="sk-..."
                                                                className="w-full bg-input border border-border rounded-lg pl-9 pr-10 py-2 text-sm focus:ring-2 focus:ring-primary/50 outline-none transition-all"
                                                            />
                                                            <button
                                                                onClick={() => toggleKeyVision(activeProvider)}
                                                                className="absolute right-3 text-muted-foreground hover:text-foreground"
                                                            >
                                                                {showKey[activeProvider] ? <EyeOff size={16} /> : <Eye size={16} />}
                                                            </button>
                                                        </div>
                                                    </div>
                                                );
                                            })()}
                                        </div>

                                    </div>
                                )}

                                {activeTab === 'system' && (
                                    <div className="space-y-8 animate-in fade-in duration-300">
                                        <div className="space-y-3">
                                            <h3 className="text-sm font-medium text-foreground">{t('settings.language')}</h3>
                                            <p className="text-xs text-muted-foreground">{t('settings.language_desc')}</p>
                                            <select
                                                value={i18n.language || 'en'}
                                                onChange={(e) => handleLanguageChange(e.target.value)}
                                                className="w-full bg-secondary text-foreground border border-border rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-primary/50 outline-none transition-all appearance-none cursor-pointer"
                                            >
                                                <option value="en">English (US)</option>
                                                <option value="zh-TW">繁體中文 (Taiwan)</option>
                                            </select>
                                        </div>

                                        <hr className="border-border/40" />

                                        <div>
                                            <h3 className="text-sm font-medium text-foreground">{t('settings.arcmind_engine')}</h3>
                                            <p className="text-xs text-muted-foreground mt-1">{t('settings.version')} Default</p>
                                        </div>
                                    </div>
                                )}

                                {activeTab === 'monitor' && (
                                    <SystemMonitor />
                                )}
                            </div>

                        </div>

                        {/* Footer */}
                        <div className="px-6 py-4 bg-card/50 border-t border-border/40 flex justify-end gap-3">
                            <button
                                onClick={onClose}
                                className="px-4 py-2 text-sm text-foreground/80 hover:bg-secondary rounded-lg transition-colors"
                            >
                                {t('settings.cancel')}
                            </button>
                            <button
                                onClick={handleSave}
                                disabled={isSaving}
                                className="px-4 py-2 text-sm bg-primary text-white rounded-lg hover:bg-primary-hover transition-colors shadow-[0_0_10px_rgba(139,92,246,0.2)] disabled:opacity-50"
                            >
                                {isSaving ? 'Saving...' : t('settings.save')}
                            </button>
                        </div>

                    </motion.div>
                </>
            )}
        </AnimatePresence>
    );
}
