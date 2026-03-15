import { memo } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import { Brain, Search, Code, Bug, Server, BarChart3, ClipboardList, Bot } from 'lucide-react';

/* ── Role → Icon mapping ─────────────────────────────────── */

const ROLE_ICONS: Record<string, React.ReactNode> = {
  ceo:      <Brain size={18} />,
  pm:       <ClipboardList size={18} />,
  search:   <Search size={18} />,
  code:     <Code size={18} />,
  qa:       <Bug size={18} />,
  devops:   <Server size={18} />,
  analysis: <BarChart3 size={18} />,
};

/* ── AgentNode Component ─────────────────────────────────── */

function AgentNodeComponent({ data, selected }: NodeProps) {
  const agent = (data as any).agent;
  const color = (data as any).color || { bg: 'rgba(148,163,184,0.08)', border: '#64748b', accent: '#94a3b8' };

  const icon = ROLE_ICONS[agent.id] || <Bot size={18} />;
  const isActive = agent.status === 'active';
  const isCeo = agent.id === 'ceo';

  return (
    <>
      {/* Input handle (top) */}
      {!isCeo && (
        <Handle
          type="target"
          position={Position.Top}
          className="!w-3 !h-3 !rounded-full !border-2"
          style={{
            background: color.accent,
            borderColor: color.border,
          }}
        />
      )}

      {/* Node body */}
      <div
        className="relative group cursor-pointer"
        style={{
          minWidth: 200,
        }}
      >
        {/* Glow effect */}
        <div
          className="absolute -inset-1 rounded-2xl opacity-0 group-hover:opacity-100 transition-opacity duration-500 blur-lg"
          style={{ background: `${color.accent}30` }}
        />

        {/* Selection ring */}
        {selected && (
          <div
            className="absolute -inset-[3px] rounded-2xl animate-pulse"
            style={{
              border: `2px solid ${color.accent}`,
              boxShadow: `0 0 20px ${color.accent}40`,
            }}
          />
        )}

        {/* Card */}
        <div
          className="relative rounded-xl p-4 backdrop-blur-xl"
          style={{
            background: `linear-gradient(135deg, ${color.bg}, rgba(15,15,25,0.95))`,
            border: `1px solid ${color.border}40`,
            boxShadow: `0 4px 24px rgba(0,0,0,0.3), inset 0 1px 0 ${color.accent}15`,
          }}
        >
          {/* Header: Icon + Name + Status */}
          <div className="flex items-center gap-3">
            <div
              className="p-2 rounded-lg"
              style={{
                background: `${color.accent}20`,
                color: color.accent,
              }}
            >
              {icon}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-white truncate">
                  {agent.name || agent.title || agent.id}
                </span>
                {agent.is_core && (
                  <span
                    className="text-[9px] font-bold px-1.5 py-0.5 rounded-full uppercase tracking-wider"
                    style={{
                      background: `${color.accent}20`,
                      color: color.accent,
                    }}
                  >
                    Core
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-[10px] text-gray-400 font-mono">{agent.id}</span>
                {(agent.model || agent.default_model) && (
                  <span className="text-[10px] text-gray-500">
                    {agent.model || agent.default_model}
                  </span>
                )}
              </div>
            </div>

            {/* Status indicator */}
            <div className="relative flex items-center">
              <div
                className="w-2.5 h-2.5 rounded-full"
                style={{
                  background: isActive ? '#22c55e' : '#6b7280',
                  boxShadow: isActive ? '0 0 8px #22c55e80' : 'none',
                }}
              />
              {isActive && (
                <div
                  className="absolute w-2.5 h-2.5 rounded-full animate-ping"
                  style={{ background: '#22c55e40' }}
                />
              )}
            </div>
          </div>

          {/* Description */}
          {agent.description && (
            <p className="text-[11px] text-gray-400 mt-2 leading-relaxed line-clamp-2">
              {agent.description}
            </p>
          )}

          {/* Tools chips */}
          {agent.allowed_tools && agent.allowed_tools.length > 0 && agent.allowed_tools[0] !== '__all__' && (
            <div className="flex flex-wrap gap-1 mt-2.5">
              {agent.allowed_tools.slice(0, 4).map((t: string) => (
                <span
                  key={t}
                  className="text-[9px] font-mono px-1.5 py-0.5 rounded"
                  style={{
                    background: 'rgba(255,255,255,0.05)',
                    color: 'rgba(255,255,255,0.5)',
                  }}
                >
                  {t}
                </span>
              ))}
              {agent.allowed_tools.length > 4 && (
                <span className="text-[9px] text-gray-500">
                  +{agent.allowed_tools.length - 4}
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Output handle (bottom) */}
      <Handle
        type="source"
        position={Position.Bottom}
        className="!w-3 !h-3 !rounded-full !border-2"
        style={{
          background: color.accent,
          borderColor: color.border,
        }}
      />
    </>
  );
}

export const AgentNode = memo(AgentNodeComponent);
