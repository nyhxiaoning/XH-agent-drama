import { useRef, useCallback, useState, useEffect, memo } from 'react';
import { X, AlertCircle, Link, Loader2, Volume2, Image as ImageIcon } from 'lucide-react';
import { useEditorStore } from '@/store/editor';
import { NODE_TYPE_CONFIG, STATUS_CONFIG } from '@/utils/constants';
import { getEstimatedCost } from '@/utils/model-config';
import type { CanvasNode } from '@/types';
import type { GridOverlayMode } from './NodeActionBar';

interface NodeCardProps {
  node: CanvasNode;
  isSelected: boolean;
  onSelect: () => void;
  onStartConnect: () => void;
  onEndConnect: () => void;
  onPositionChange: (x: number, y: number) => void;
  onGenerate: () => void;
  onHeightChange: (id: string, height: number) => void;
  scale: number;
  gridMode?: GridOverlayMode;
}

export const NodeCard = memo(function NodeCard({ node, isSelected, onSelect, onStartConnect, onEndConnect, onPositionChange, onGenerate, onHeightChange, scale, gridMode = 'none' }: NodeCardProps) {
  const dragState = useRef<{ startX: number; startY: number; nodeX: number; nodeY: number; dragging: boolean } | null>(null);
  const activeMoveRef = useRef<((e: MouseEvent) => void) | null>(null);
  const activeUpRef = useRef<(() => void) | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const deleteNode = useEditorStore((s) => s.deleteNode);
  const connectingFrom = useEditorStore((s) => s.connectingFrom);
  const modelPricing = useEditorStore((s) => s.modelPricing);
  const [isHovered, setIsHovered] = useState(false);
  const [mediaError, setMediaError] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  useEffect(() => {
    setMediaError(false);
  }, [node.result_url, node.thumbnail_url]);

  useEffect(() => {
    const el = cardRef.current;
    if (!el) return;
    const update = () => {
      const h = el.offsetHeight;
      if (h > 0 && Math.abs(h - node.height) > 2) {
        onHeightChange(node.id, h);
      }
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [node.id, node.height, onHeightChange]);

  const cfg = NODE_TYPE_CONFIG[node.node_type as keyof typeof NODE_TYPE_CONFIG] || { label: '节点', icon: '📦', color: '#6b7280', desc: '' };
  const statusCfg = STATUS_CONFIG[node.status as keyof typeof STATUS_CONFIG] || { label: node.status || '等待中', color: '#6b7280', bgClass: 'bg-node-pending' };

  useEffect(() => {
    return () => {
      if (activeMoveRef.current) document.removeEventListener('mousemove', activeMoveRef.current);
      if (activeUpRef.current) document.removeEventListener('mouseup', activeUpRef.current);
    };
  }, []);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('.no-drag')) return;

    // 整个卡片均可拖动移动节点；连线仅通过右侧锚点触发
    e.stopPropagation();
    dragState.current = {
      startX: e.clientX,
      startY: e.clientY,
      nodeX: node.x,
      nodeY: node.y,
      dragging: false,
    };

    const handleMouseMove = (ev: MouseEvent) => {
      if (!dragState.current) return;
      const dx = (ev.clientX - dragState.current.startX) / scale;
      const dy = (ev.clientY - dragState.current.startY) / scale;
      const threshold = 3;
      if (!dragState.current.dragging && Math.abs(dx) + Math.abs(dy) < threshold) return;
      dragState.current.dragging = true;
      onPositionChange(dragState.current.nodeX + dx, dragState.current.nodeY + dy);
    };
    const handleMouseUp = () => {
      if (dragState.current && !dragState.current.dragging) {
        onSelect();
      }
      dragState.current = null;
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  }, [node.x, node.y, onSelect, onPositionChange, scale]);

  const handleConnectStart = (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    onStartConnect();
  };

  const handleNodeMouseUp = () => {
    if (connectingFrom && connectingFrom !== node.id) {
      onEndConnect();
    }
  };

  const isProcessing = node.status === 'processing';
  const statusBg = statusCfg.bgClass;

  const isVisualMedia = node.node_type === 'image' || node.node_type === 'storyboard' || node.node_type === 'character' || node.node_type === 'scene';
  const isVideo = node.node_type === 'video';
  const isAudio = node.node_type === 'audio';
  const isScript = node.node_type === 'script';
  const hasResult = node.result_url && node.status === 'success';

  const isBorderlessMedia = hasResult && (isVisualMedia || isVideo) && !mediaError;

  return (
    <div
      ref={cardRef}
      className={`node-card ${isProcessing ? 'node-processing-ring' : ''} ${isBorderlessMedia ? 'node-card-borderless' : ''} ${isSelected && !isProcessing ? 'ring-2 ring-accent/50' : ''}`}
      style={{
        left: node.x,
        top: node.y,
        width: node.width,
        zIndex: isSelected ? 50 : 10,
      }}
      onMouseDown={handleMouseDown}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onMouseUp={handleNodeMouseUp}
    >
      <div className="node-card-label">
        <span className="text-sm">{cfg.icon}</span>
        <span className="text-xs font-semibold text-theme-main truncate max-w-[140px]">{node.title || cfg.label}</span>
        <div className={`status-dot ${statusBg} ${node.status === 'processing' ? 'animate-pulse' : ''} shrink-0`} />
        {isProcessing && (
          <Loader2 size={12} className="animate-spin text-node-processing ml-auto shrink-0" />
        )}
      </div>

      {isBorderlessMedia ? (
        <div className="node-card-media-wrap">
          {isVisualMedia && !mediaError ? (
            <img
              src={node.thumbnail_url || node.result_url}
              alt=""
              onError={() => setMediaError(true)}
              draggable={false}
            />
          ) : isVideo && !mediaError ? (
            <video
              src={node.result_url}
              preload="metadata"
              muted
              onError={() => setMediaError(true)}
            />
          ) : null}

          {gridMode !== 'none' && (
            <div className="absolute inset-0 pointer-events-none z-10">
              {gridMode === 'rule-of-thirds' && (
                <>
                  <div className="absolute top-0 bottom-0 left-1/3 w-px bg-white/40" />
                  <div className="absolute top-0 bottom-0 left-2/3 w-px bg-white/40" />
                  <div className="absolute left-0 right-0 top-1/3 h-px bg-white/40" />
                  <div className="absolute left-0 right-0 top-2/3 h-px bg-white/40" />
                </>
              )}
              {gridMode === 'grid-12' && (
                <>
                  <div className="absolute top-0 bottom-0 left-1/4 w-px bg-white/40" />
                  <div className="absolute top-0 bottom-0 left-2/4 w-px bg-white/40" />
                  <div className="absolute top-0 bottom-0 left-3/4 w-px bg-white/40" />
                  <div className="absolute left-0 right-0 top-1/3 h-px bg-white/40" />
                  <div className="absolute left-0 right-0 top-2/3 h-px bg-white/40" />
                </>
              )}
            </div>
          )}

          {isHovered && (
            <div className="absolute bottom-1.5 right-2 text-[9px] text-success bg-black/40 backdrop-blur-sm px-1.5 py-0.5 rounded-full flex items-center gap-0.5 pointer-events-none">
              ✓ 已完成
            </div>
          )}
        </div>
      ) : (
        <div className="px-3 py-2.5 min-h-[60px]">
          {node.error_msg ? (
            <div className="flex items-start gap-1.5 text-[10px] text-error">
              <AlertCircle size={12} className="shrink-0 mt-0.5" />
              <span className="leading-relaxed">{node.error_msg}</span>
            </div>
          ) : node.status === 'processing' ? (
            <div className="space-y-1.5">
              <div className="text-[10px] text-node-processing flex items-center gap-1">
                <Loader2 size={10} className="animate-spin" /> AI正在生成...
              </div>
              <div className="h-1 bg-panel-border rounded-full overflow-hidden">
                <div className="h-full bg-node-processing rounded-full transition-all duration-300" style={{ width: `${node.progress}%` }} />
              </div>
            </div>
          ) : hasResult ? (
            <div className="text-[10px] space-y-1.5">
              {isAudio ? (
                <div className="w-full bg-canvas-bg rounded-xl p-2 flex items-center gap-2">
                  <Volume2 size={14} className="text-accent shrink-0" />
                  <audio src={node.result_url} controls className="h-6 w-full" onError={() => setMediaError(true)} />
                </div>
              ) : (
                <div className="w-full h-16 bg-canvas-bg rounded-xl flex flex-col items-center justify-center gap-1 text-theme-sub px-2 text-center">
                  <ImageIcon size={14} />
                  <span className="text-[10px]">结果已生成</span>
                  {node.result_url && (
                    <>
                      <button
                        className="text-[9px] text-accent hover:underline"
                        onClick={(e) => { e.stopPropagation(); setMediaError(false); }}
                      >
                        重新加载
                      </button>
                      <a
                        href={node.result_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-[9px] text-accent hover:underline truncate max-w-full"
                        onClick={(e) => e.stopPropagation()}
                      >
                        查看原图 →
                      </a>
                    </>
                  )}
                </div>
              )}
              <div className="text-success flex items-center gap-1">✓ 生成完成</div>
            </div>
          ) : isScript ? (
            <div className="text-[10px] text-theme-sub leading-relaxed line-clamp-4 font-mono">{node.prompt || '点击编辑剧本内容...'}</div>
          ) : node.prompt ? (
            <div className="text-[10px] text-theme-sub leading-relaxed line-clamp-3 font-mono">{node.prompt}</div>
          ) : (
            <div className="text-[10px] text-theme-hint italic">点击编辑Prompt...</div>
          )}
        </div>
      )}

      {/* 删除按钮 — 悬停时显示在卡片右上角 */}
      {isHovered && !showDeleteConfirm && (
        <button
          className="no-drag absolute -top-3 -right-3 w-7 h-7 rounded-full bg-error/90 hover:bg-error text-white flex items-center justify-center shadow-lg transition-all hover:scale-110 z-20"
          onClick={(e) => { e.stopPropagation(); setShowDeleteConfirm(true); }}
          title="删除节点"
        >
          <X size={16} />
        </button>
      )}

      {/* 删除确认弹窗 */}
      {showDeleteConfirm && (
        <div
          className="no-drag absolute -top-3 left-1/2 -translate-x-1/2 z-40 glass rounded-2xl shadow-soft-lg border border-panel-border/50 px-6 py-5 flex flex-col items-center gap-4 whitespace-nowrap"
          onClick={(e) => e.stopPropagation()}
        >
          <span className="text-sm font-medium text-theme-main">确定删除「{node.title || cfg.label}」节点？</span>
          <div className="flex items-center gap-3">
            <button
              className="px-5 py-2 rounded-xl bg-error hover:bg-error/80 text-white text-sm font-medium transition-colors"
              onClick={(e) => { e.stopPropagation(); deleteNode(node.id); setShowDeleteConfirm(false); }}
            >
              确定删除
            </button>
            <button
              className="px-5 py-2 rounded-xl bg-panel-border/30 hover:bg-panel-border/50 text-theme-main text-sm font-medium transition-colors"
              onClick={(e) => { e.stopPropagation(); setShowDeleteConfirm(false); }}
            >
              取消
            </button>
          </div>
        </div>
      )}

      {/* 连线锚点 */}
      <div
        className="no-drag absolute -right-2.5 top-1/2 -translate-y-1/2 w-5 h-5 rounded-full glass border border-accent cursor-crosshair hover:bg-accent hover:scale-110 transition-all flex items-center justify-center shadow-soft"
        onMouseDown={handleConnectStart}
        title="拖拽连线"
      >
        <Link size={8} className="text-accent" />
      </div>
    </div>
  );
});
