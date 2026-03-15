import { Plus, Link, Trash2, LayoutGrid, RotateCcw } from 'lucide-react';
import { useAgentFlowStore } from '../../store/agentFlowStore';

export function AgentToolbar() {
  const { reLayout, fetchAgents, agents } = useAgentFlowStore();

  return (
    <div className="absolute top-4 left-4 z-20 flex flex-col gap-2">
      {/* Agent count badge */}
      <div
        className="flex items-center justify-center rounded-xl px-3 py-2 text-[11px] font-semibold tracking-wider"
        style={{
          background: 'rgba(15,15,25,0.9)',
          border: '1px solid rgba(255,255,255,0.06)',
          color: 'rgba(255,255,255,0.6)',
          backdropFilter: 'blur(12px)',
        }}
      >
        {agents.length} Agents
      </div>

      {/* Tool buttons */}
      <div
        className="flex flex-col gap-1 rounded-xl p-1.5"
        style={{
          background: 'rgba(15,15,25,0.9)',
          border: '1px solid rgba(255,255,255,0.06)',
          backdropFilter: 'blur(12px)',
        }}
      >
        <ToolButton icon={<Plus size={16} />} label="添加 Agent" onClick={() => {}} />
        <ToolButton icon={<Link size={16} />} label="新增連線" onClick={() => {}} />
        <ToolButton icon={<Trash2 size={16} />} label="刪除選中" onClick={() => {}} />

        <div className="h-px bg-white/5 my-1" />

        <ToolButton icon={<LayoutGrid size={16} />} label="自動佈局" onClick={reLayout} />
        <ToolButton icon={<RotateCcw size={16} />} label="重新載入" onClick={fetchAgents} />
      </div>
    </div>
  );
}

function ToolButton({
  icon,
  label,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      className="flex items-center gap-2 px-2.5 py-2 rounded-lg text-gray-400 hover:text-white hover:bg-white/10 transition-all text-[11px] group"
    >
      <span className="group-hover:scale-110 transition-transform">{icon}</span>
      <span className="hidden lg:inline">{label}</span>
    </button>
  );
}
