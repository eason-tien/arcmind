import { motion, AnimatePresence } from 'framer-motion';
import { X, Bot, Crown, Wrench, Cpu, FileText } from 'lucide-react';
import { useAgentFlowStore, getAgentColor } from '../../store/agentFlowStore';

export function AgentDetailPanel() {
  const { selectedNodeId, agents, selectNode } = useAgentFlowStore();
  const agent = agents.find((a) => a.id === selectedNodeId);

  return (
    <AnimatePresence>
      {agent && (
        <motion.div
          initial={{ x: 320, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: 320, opacity: 0 }}
          transition={{ type: 'spring', bounce: 0, duration: 0.35 }}
          className="absolute top-0 right-0 h-full w-80 z-20 border-l border-white/5"
          style={{
            background: 'linear-gradient(180deg, rgba(15,15,25,0.97), rgba(10,10,20,0.99))',
            backdropFilter: 'blur(24px)',
          }}
        >
          {/* Header */}
          <div className="flex items-center justify-between p-4 border-b border-white/5">
            <div className="flex items-center gap-2">
              <div
                className="p-2 rounded-lg"
                style={{
                  background: `${getAgentColor(agent.id).accent}20`,
                  color: getAgentColor(agent.id).accent,
                }}
              >
                {(agent.id === 'ceo' || agent.id === 'main') ? <Crown size={16} /> : <Bot size={16} />}
              </div>
              <div>
                <h3 className="text-sm font-semibold text-white">
                  {agent.name || agent.title || agent.id}
                </h3>
                <span className="text-[10px] text-gray-500 font-mono">{agent.id}</span>
              </div>
            </div>
            <button
              onClick={() => selectNode(null)}
              className="p-1.5 text-gray-400 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
            >
              <X size={16} />
            </button>
          </div>

          {/* Content */}
          <div className="overflow-y-auto h-[calc(100%-60px)] p-4 space-y-5">
            {/* Status */}
            <Section title="狀態">
              <div className="flex items-center gap-2">
                <div
                  className="w-2 h-2 rounded-full"
                  style={{
                    background: agent.status === 'active' ? '#22c55e' : '#6b7280',
                    boxShadow: agent.status === 'active' ? '0 0 8px #22c55e80' : 'none',
                  }}
                />
                <span className="text-sm text-gray-300 capitalize">{agent.status || 'active'}</span>
                {agent.is_core && (
                  <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-purple-500/20 text-purple-400 uppercase">
                    Core
                  </span>
                )}
              </div>
            </Section>

            {/* Model */}
            <Section title="模型" icon={<Cpu size={14} />}>
              <div className="text-sm text-gray-300 font-mono bg-white/5 rounded-lg px-3 py-2">
                {agent.model || agent.default_model || 'auto'}
              </div>
            </Section>

            {/* Description */}
            {agent.description && (
              <Section title="描述" icon={<FileText size={14} />}>
                <p className="text-sm text-gray-400 leading-relaxed">{agent.description}</p>
              </Section>
            )}

            {/* Capabilities */}
            {agent.capabilities && agent.capabilities.length > 0 && (
              <Section title="能力">
                <div className="flex flex-wrap gap-1.5">
                  {agent.capabilities.map((c) => (
                    <span
                      key={c}
                      className="text-[10px] font-mono px-2 py-1 rounded-md bg-indigo-500/10 text-indigo-400 border border-indigo-500/20"
                    >
                      {c}
                    </span>
                  ))}
                </div>
              </Section>
            )}

            {/* Allowed Tools */}
            <Section title="可用工具" icon={<Wrench size={14} />}>
              {agent.allowed_tools && agent.allowed_tools.length > 0 ? (
                agent.allowed_tools[0] === '__all__' ? (
                  <span className="text-sm text-emerald-400">所有工具</span>
                ) : (
                  <div className="flex flex-wrap gap-1.5 max-h-40 overflow-y-auto">
                    {agent.allowed_tools.map((t) => (
                      <span
                        key={t}
                        className="text-[10px] font-mono px-2 py-1 rounded-md bg-white/5 text-gray-400"
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                )
              ) : (
                <span className="text-sm text-gray-500">未配置</span>
              )}
            </Section>

            {/* System Prompt preview */}
            {agent.system_prompt && (
              <Section title="System Prompt">
                <div className="text-[11px] text-gray-500 font-mono bg-white/5 rounded-lg p-3 max-h-32 overflow-y-auto leading-relaxed whitespace-pre-wrap">
                  {agent.system_prompt.slice(0, 500)}
                  {agent.system_prompt.length > 500 && '...'}
                </div>
              </Section>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/* ── Section helper ──────────────────────────────────────── */

function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-center gap-1.5 text-[11px] font-semibold text-gray-500 uppercase tracking-wider mb-2">
        {icon}
        {title}
      </div>
      {children}
    </div>
  );
}
