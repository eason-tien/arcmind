import { useEffect, useCallback, useMemo } from 'react';
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  type NodeMouseHandler,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { useAgentFlowStore, getAgentColor } from '../../store/agentFlowStore';
import { AgentNode } from './AgentNode';
import { PipelineEdge } from './PipelineEdge';
import { AgentDetailPanel } from './AgentDetailPanel';
import { AgentToolbar } from './AgentToolbar';

/* ── Custom node/edge types (must be stable ref) ─────────── */

const nodeTypes = { agentNode: AgentNode };
const edgeTypes = { pipelineEdge: PipelineEdge };

/* ── Main Component ──────────────────────────────────────── */

export function AgentWorkflowEditor() {
  const {
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onConnect,
    selectNode,
    fetchAgents,
    loading,
    selectedNodeId,
  } = useAgentFlowStore();

  useEffect(() => {
    fetchAgents();
  }, [fetchAgents]);

  const onNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      selectNode(node.id);
    },
    [selectNode]
  );

  const onPaneClick = useCallback(() => {
    selectNode(null);
  }, [selectNode]);

  /* MiniMap node color */
  const miniMapNodeColor = useCallback((node: any) => {
    const agentId = node.id;
    return getAgentColor(agentId).accent;
  }, []);

  /* Default viewport — center on CEO */
  const defaultViewport = useMemo(() => ({ x: 500, y: 80, zoom: 1 }), []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full w-full">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-purple-500/30 border-t-purple-500 rounded-full animate-spin" />
          <span className="text-sm text-gray-400">載入 Agent 拓撲...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="relative h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        defaultViewport={defaultViewport}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        minZoom={0.3}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        className="agent-workflow-canvas"
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={20}
          size={1}
          color="rgba(255,255,255,0.03)"
        />

        <Controls
          position="bottom-right"
          showInteractive={false}
          className="agent-flow-controls"
        />

        <MiniMap
          position="bottom-left"
          nodeColor={miniMapNodeColor}
          maskColor="rgba(0,0,0,0.7)"
          className="agent-flow-minimap"
          pannable
          zoomable
        />
      </ReactFlow>

      {/* Overlays */}
      <AgentToolbar />
      <AgentDetailPanel />

      {/* Legend */}
      <div
        className="absolute bottom-4 right-28 z-10 flex items-center gap-4 px-4 py-2 rounded-xl text-[10px]"
        style={{
          background: 'rgba(15,15,25,0.85)',
          border: '1px solid rgba(255,255,255,0.05)',
          backdropFilter: 'blur(8px)',
        }}
      >
        <LegendDot color="#6366f1" label="delegate" />
        <LegendDot color="#c084fc" label="pipeline" />
        <LegendDot color="#4ade80" label="handoff" />
        <LegendDot color="#f87171" label="escalate" />
      </div>
    </div>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <div
        className="w-2 h-2 rounded-full"
        style={{ background: color, boxShadow: `0 0 6px ${color}60` }}
      />
      <span className="text-gray-400 font-mono">{label}</span>
    </div>
  );
}
