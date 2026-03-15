import { AgentWorkflowEditor } from '../Agents/AgentWorkflowEditor';

/**
 * Agent 管理頁面 — 節點拉線式工作流編輯器
 *
 * 替代舊版卡片網格，使用 React Flow 展示 Agent 拓撲、
 * 委派關係、Pipeline 連線、即時狀態。
 */
export function AgentManager() {
  return (
    <div className="flex flex-col h-full w-full bg-background/50 relative overflow-hidden">
      {/* Full-bleed canvas */}
      <AgentWorkflowEditor />
    </div>
  );
}
