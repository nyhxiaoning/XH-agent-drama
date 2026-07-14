import { memo, useState, useRef, useEffect, useCallback } from 'react';
import {
  Play, RotateCcw, Brush, Grid3X3, Grid2X2,
  Film, Settings, Loader2, Paperclip, AtSign,
} from 'lucide-react';
import type { CanvasNode } from '@/types';

export type GridOverlayMode = 'none' | 'rule-of-thirds' | 'grid-12';

export interface NodeActionBarProps {
  node: CanvasNode;
  /** 屏幕 X 坐标（节点左边缘） */
  screenX: number;
  /** 屏幕 Y 坐标（节点顶部） */
  screenY: number;
  scale: number;
  /** 当前网格叠加模式 */
  gridMode: GridOverlayMode;
  onGridModeChange: (mode: GridOverlayMode) => void;
  /** 打开局部重绘 */
  onInpaint: () => void;
  /** 打开运镜/影视参数 */
  onCinematic: () => void;
  /** 打开完整属性面板 */
  onOpenProperty: () => void;
  /** 生成/重新生成 */
  onGenerate: () => void;
  /** 快捷上传参考图 */
  onQuickUpload?: () => void;
  /** 快捷引用资产 */
  onQuickReference?: () => void;
}

// 九宫格循环切换
const GRID_CYCLE: GridOverlayMode[] = ['none', 'rule-of-thirds', 'grid-12'];
const GRID_LABELS: Record<GridOverlayMode, string> = {
  'none': '关闭网格',
  'rule-of-thirds': '九宫格',
  'grid-12': '十二宫格',
};

export const NodeActionBar = memo(function NodeActionBar({
  node,
  screenX,
  screenY,
  scale,
  gridMode,
  onGridModeChange,
  onInpaint,
  onCinematic,
  onOpenProperty,
  onGenerate,
  onQuickUpload,
  onQuickReference,
}: NodeActionBarProps) {
  const barRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ x: screenX, y: screenY });

  // 根据节点位置计算工具栏位置（在节点上方）
  useEffect(() => {
    const barEl = barRef.current;
    const barH = barEl?.offsetHeight ?? 52;
    const scaleFactor = Math.max(0.65, Math.min(1.5, scale));
    const gap = 8;
    let x = screenX;
    // 视觉高度 = barH * scaleFactor，需要让视觉底边在节点上方 gap 像素处
    let y = screenY - barH * scaleFactor - gap;

    // 边界检测
    const vw = window.innerWidth;
    if (x + 480 > vw - 16) x = vw - 496;
    if (x < 16) x = 16;
    if (y < 16) y = screenY + gap; // 放不下就放下面

    setPosition({ x, y });
  }, [screenX, screenY, scale]);

  const handleGridToggle = useCallback(() => {
    const idx = GRID_CYCLE.indexOf(gridMode);
    const next = GRID_CYCLE[(idx + 1) % GRID_CYCLE.length];
    onGridModeChange(next);
  }, [gridMode, onGridModeChange]);

  const isProcessing = node.status === 'processing';
  const isVisualMedia = node.node_type === 'image' || node.node_type === 'storyboard' || node.node_type === 'character' || node.node_type === 'scene';
  const isVideo = node.node_type === 'video';
  const hasResult = node.result_url && node.status === 'success';
  // 可拥有参考图的节点类型
  const canHaveReference = isVisualMedia || isVideo;

  // 按钮基础样式
  const btnClass = "relative flex items-center justify-center w-10 h-10 rounded-xl transition-all duration-150 shrink-0";
  const btnDefault = `${btnClass} text-theme-sub hover:bg-accent/12 hover:text-accent`;
  const btnActive = `${btnClass} bg-accent/15 text-accent`;

  return (
    <div
      ref={barRef}
      className="node-action-bar no-pan"
      style={{
        left: position.x,
        top: position.y,
        transform: `scale(${Math.max(0.65, Math.min(1.5, scale))})`,
        transformOrigin: 'left top',
        zIndex: 60,
      }}
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
    >
      {/* 生成/重新生成 */}
      <button
        className={isProcessing ? `${btnClass} text-theme-hint cursor-not-allowed` : 'action-btn-primary'}
        onClick={(e) => { e.stopPropagation(); if (!isProcessing) onGenerate(); }}
        disabled={isProcessing}
        title={node.status === 'success' ? '重新生成' : '生成'}
      >
        {isProcessing ? <Loader2 size={18} className="animate-spin" /> : (node.status === 'success' ? <RotateCcw size={18} /> : <Play size={18} />)}
      </button>

      <div className="action-bar-divider" />

      {/* 上传参考图 — 可生成视觉媒体的节点均可上传 */}
      {canHaveReference && onQuickUpload && (
        <button
          className={btnDefault}
          onClick={(e) => { e.stopPropagation(); onQuickUpload(); }}
          title="上传参考图"
        >
          <Paperclip size={18} />
        </button>
      )}

      {/* 引用资产 */}
      {canHaveReference && onQuickReference && (
        <button
          className={btnDefault}
          onClick={(e) => { e.stopPropagation(); onQuickReference(); }}
          title="引用资产"
        >
          <AtSign size={18} />
        </button>
      )}

      {/* 局部重绘 — 仅图片类型且已生成成功 */}
      {isVisualMedia && hasResult && (
        <button
          className={btnDefault}
          onClick={(e) => { e.stopPropagation(); onInpaint(); }}
          title="局部重绘"
        >
          <Brush size={18} />
        </button>
      )}

      {/* 运镜/影视参数 — 仅视频类型 */}
      {isVideo && (
        <button
          className={btnDefault}
          onClick={(e) => { e.stopPropagation(); onCinematic(); }}
          title="运镜 & 影视参数"
        >
          <Film size={18} />
        </button>
      )}

      {/* 九宫格/十二宫格 — 仅可视媒体 */}
      {isVisualMedia && (
        <button
          className={gridMode !== 'none' ? btnActive : btnDefault}
          onClick={(e) => { e.stopPropagation(); handleGridToggle(); }}
          title={GRID_LABELS[gridMode]}
        >
          {gridMode === 'grid-12' ? <Grid2X2 size={18} /> : <Grid3X3 size={18} />}
          {gridMode !== 'none' && (
            <span className="action-bar-badge">{gridMode === 'rule-of-thirds' ? '9' : '12'}</span>
          )}
        </button>
      )}

      {/* 完整属性面板 */}
      <button
        className={btnDefault}
        onClick={(e) => { e.stopPropagation(); onOpenProperty(); }}
        title="详细设置"
      >
        <Settings size={18} />
      </button>
    </div>
  );
});
