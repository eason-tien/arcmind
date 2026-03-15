import { memo, useMemo } from 'react';
import { BaseEdge, getSmoothStepPath, type EdgeProps } from '@xyflow/react';

/**
 * Custom animated pipeline edge with:
 * - Gradient stroke matching source/target agent colors
 * - Flowing dot animation
 * - Delegation type label
 */
function PipelineEdgeComponent({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  selected,
}: EdgeProps) {
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    borderRadius: 20,
  });

  const label = (data as any)?.label || '';
  const gradientId = `edge-gradient-${id}`;
  const animId = `edge-anim-${id}`;

  // Label color per type
  const labelStyle = useMemo(() => {
    switch (label) {
      case 'pipeline': return { bg: 'rgba(168,85,247,0.2)', color: '#c084fc' };
      case 'handoff':  return { bg: 'rgba(34,197,94,0.2)',  color: '#4ade80' };
      case 'escalate': return { bg: 'rgba(239,68,68,0.2)',  color: '#f87171' };
      default:         return { bg: 'rgba(99,102,241,0.2)', color: '#818cf8' };
    }
  }, [label]);

  return (
    <>
      {/* SVG defs for gradient + animation */}
      <defs>
        <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#818cf8" stopOpacity="0.6" />
          <stop offset="100%" stopColor="#c084fc" stopOpacity="0.6" />
        </linearGradient>
      </defs>

      {/* Glow layer */}
      <BaseEdge
        id={`${id}-glow`}
        path={edgePath}
        style={{
          stroke: selected ? '#818cf8' : '#818cf840',
          strokeWidth: selected ? 6 : 4,
          filter: 'blur(4px)',
          fill: 'none',
        }}
      />

      {/* Main edge */}
      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          stroke: `url(#${gradientId})`,
          strokeWidth: selected ? 2.5 : 1.5,
          fill: 'none',
        }}
      />

      {/* Animated flowing dot */}
      <circle r="3" fill="#818cf8" filter="drop-shadow(0 0 4px #818cf880)">
        <animateMotion
          id={animId}
          dur="3s"
          repeatCount="indefinite"
          path={edgePath}
        />
      </circle>

      {/* Label */}
      {label && (
        <foreignObject
          x={labelX - 30}
          y={labelY - 10}
          width={60}
          height={20}
          className="overflow-visible pointer-events-none"
        >
          <div
            className="flex items-center justify-center rounded-full text-[9px] font-mono px-2 py-0.5 whitespace-nowrap"
            style={{
              background: labelStyle.bg,
              color: labelStyle.color,
              backdropFilter: 'blur(8px)',
            }}
          >
            {label}
          </div>
        </foreignObject>
      )}
    </>
  );
}

export const PipelineEdge = memo(PipelineEdgeComponent);
