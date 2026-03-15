import { create } from 'zustand';
import {
  type Node,
  type Edge,
  type OnNodesChange,
  type OnEdgesChange,
  type Connection,
  applyNodeChanges,
  applyEdgeChanges,
  addEdge,
  MarkerType,
} from '@xyflow/react';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8100';

/* ── Types ────────────────────────────────────────────────── */

export interface AgentData {
  id: string;
  name: string;
  title?: string;
  role?: string;
  model?: string;
  default_model?: string;
  description?: string;
  status?: string;
  allowed_tools?: string[];
  capabilities?: string[];
  enabled?: boolean;
  is_core?: boolean;
  system_prompt?: string;
}

/* ── Color palette per agent role ─────────────────────────── */

const ROLE_COLORS: Record<string, { bg: string; border: string; accent: string }> = {
  ceo:     { bg: 'rgba(234,179,8,0.08)',   border: '#ca8a04', accent: '#eab308' },
  pm:      { bg: 'rgba(168,85,247,0.08)',   border: '#9333ea', accent: '#a855f7' },
  search:  { bg: 'rgba(59,130,246,0.08)',   border: '#2563eb', accent: '#3b82f6' },
  code:    { bg: 'rgba(34,197,94,0.08)',    border: '#16a34a', accent: '#22c55e' },
  qa:      { bg: 'rgba(249,115,22,0.08)',   border: '#ea580c', accent: '#f97316' },
  devops:  { bg: 'rgba(236,72,153,0.08)',   border: '#db2777', accent: '#ec4899' },
  analysis:{ bg: 'rgba(6,182,212,0.08)',    border: '#0891b2', accent: '#06b6d4' },
  default: { bg: 'rgba(148,163,184,0.08)',  border: '#64748b', accent: '#94a3b8' },
};

export function getAgentColor(role: string) {
  return ROLE_COLORS[role] || ROLE_COLORS.default;
}

/* ── Default delegation edges (CEO → Sub-agents) ─────────── */

const DEFAULT_EDGES: Array<{ source: string; target: string; label?: string }> = [
  { source: 'ceo', target: 'pm',       label: 'delegate' },
  { source: 'ceo', target: 'search',   label: 'delegate' },
  { source: 'ceo', target: 'code',     label: 'delegate' },
  { source: 'ceo', target: 'analysis', label: 'delegate' },
  { source: 'pm',  target: 'code',     label: 'pipeline' },
  { source: 'pm',  target: 'qa',       label: 'pipeline' },
  { source: 'pm',  target: 'devops',   label: 'pipeline' },
  { source: 'pm',  target: 'search',   label: 'pipeline' },
  { source: 'code', target: 'qa',      label: 'handoff' },
];

/* ── Auto-layout helpers ─────────────────────────────────── */

function autoLayout(agents: AgentData[]): Node[] {
  const tiers: Record<string, number> = {
    ceo: 0, pm: 1, search: 1, analysis: 1,
    code: 2, qa: 2, devops: 2,
  };

  const tierCounts: Record<number, number> = {};
  const tierIndex: Record<number, number> = {};

  const sorted = [...agents].sort((a, b) => {
    const ta = tiers[a.id] ?? 2;
    const tb = tiers[b.id] ?? 2;
    return ta - tb;
  });

  // Count nodes per tier
  sorted.forEach((a) => {
    const t = tiers[a.id] ?? 3;
    tierCounts[t] = (tierCounts[t] || 0) + 1;
  });

  return sorted.map((agent) => {
    const tier = tiers[agent.id] ?? 3;
    const count = tierCounts[tier] || 1;
    const idx = tierIndex[tier] || 0;
    tierIndex[tier] = idx + 1;

    const xSpacing = 280;
    const ySpacing = 200;
    const totalWidth = (count - 1) * xSpacing;
    const startX = -totalWidth / 2;

    return {
      id: agent.id,
      type: 'agentNode',
      position: { x: startX + idx * xSpacing, y: tier * ySpacing },
      data: { agent, color: getAgentColor(agent.id) },
    };
  });
}

/* ── Store ────────────────────────────────────────────────── */

interface AgentFlowState {
  nodes: Node[];
  edges: Edge[];
  selectedNodeId: string | null;
  agents: AgentData[];
  loading: boolean;

  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: (conn: Connection) => void;
  selectNode: (id: string | null) => void;

  fetchAgents: () => Promise<void>;
  reLayout: () => void;
}

export const useAgentFlowStore = create<AgentFlowState>((set, get) => ({
  nodes: [],
  edges: [],
  selectedNodeId: null,
  agents: [],
  loading: true,

  onNodesChange: (changes) => {
    set({ nodes: applyNodeChanges(changes, get().nodes) });
  },

  onEdgesChange: (changes) => {
    set({ edges: applyEdgeChanges(changes, get().edges) });
  },

  onConnect: (connection) => {
    const newEdge = {
      ...connection,
      type: 'pipelineEdge',
      animated: true,
      markerEnd: { type: MarkerType.ArrowClosed, color: '#818cf8' },
      data: { label: 'delegate' },
    };
    set({ edges: addEdge(newEdge, get().edges) });
  },

  selectNode: (id) => set({ selectedNodeId: id }),

  fetchAgents: async () => {
    try {
      set({ loading: true });

      let agentList: AgentData[] = [];

      // Try dedicated endpoint
      try {
        const res = await fetch(`${API_BASE}/v1/agents`);
        if (res.ok) {
          const data = await res.json();
          agentList = data.agents || [];
        }
      } catch { /* fallback */ }

      // Fallback from healthz
      if (agentList.length === 0) {
        try {
          const res = await fetch(`${API_BASE}/healthz`);
          const h = await res.json();
          if (h.lifecycle?.registered_agents) {
            agentList = h.lifecycle.registered_agents;
          }
        } catch { /* use defaults */ }
      }

      // Hardcoded defaults
      if (agentList.length === 0) {
        agentList = [
          { id: 'ceo', name: 'CEO (執行長)', role: 'ceo', is_core: true, status: 'active', description: '最高決策者，負責任務分派與整合' },
          { id: 'pm', name: '產品經理', role: 'pm', is_core: true, status: 'active', description: '需求分析、任務拆解、優先級排序' },
          { id: 'search', name: '搜尋專員', role: 'search', is_core: true, status: 'active', description: '網路搜尋、資料彙整、新聞追蹤' },
          { id: 'analysis', name: '數據分析師', role: 'analysis', is_core: true, status: 'active', description: '數據分析、報告生成、文件摘要' },
          { id: 'code', name: '軟體工程師', role: 'code', is_core: true, status: 'active', description: '代碼生成、調試、Code Review、重構' },
          { id: 'qa', name: 'QA 工程師', role: 'qa', is_core: true, status: 'active', description: '測試生成、Bug 驗證、回歸測試' },
          { id: 'devops', name: 'DevOps 工程師', role: 'devops', is_core: true, status: 'active', description: '部署、CI/CD、環境管理、監控' },
        ];
      }

      const nodes = autoLayout(agentList);
      const edges: Edge[] = DEFAULT_EDGES
        .filter((e) => agentList.some((a) => a.id === e.source) && agentList.some((a) => a.id === e.target))
        .map((e) => ({
          id: `${e.source}-${e.target}`,
          source: e.source,
          target: e.target,
          type: 'pipelineEdge',
          animated: true,
          markerEnd: { type: MarkerType.ArrowClosed, color: '#818cf8', width: 16, height: 16 },
          data: { label: e.label },
        }));

      set({ agents: agentList, nodes, edges, loading: false });
    } catch (err) {
      console.error('Failed to fetch agents:', err);
      set({ loading: false });
    }
  },

  reLayout: () => {
    const { agents } = get();
    const nodes = autoLayout(agents);
    set({ nodes });
  },
}));
