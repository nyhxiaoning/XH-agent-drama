/**
 * 聚焦特写裁剪框交互组件
 * 当节点 config.preset_focus_crop === true 时显示，
 * 让用户在图片上拖拽选择裁剪区域，然后调用后端 API 执行裁剪。
 */
import { useState, useRef, useEffect, useCallback } from 'react';
import { Focus, Loader2, X, Check } from 'lucide-react';
import { api } from '@/utils/api';
import { useEditorStore } from '@/store/editor';
import type { CanvasNode } from '@/types';

interface CropOverlayProps {
  node: CanvasNode;
  onClose: () => void;
}

interface CropRegion {
  x: number;
  y: number;
  w: number;
  h: number;
}

export function CropOverlay({ node, onClose }: CropOverlayProps) {
  const [region, setRegion] = useState<CropRegion>({ x: 20, y: 20, w: 60, h: 60 });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const dragStart = useRef({ x: 0, y: 0 });

  // 外部点击关闭
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (overlayRef.current && !overlayRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [onClose]);

  // 自动清除提示
  useEffect(() => {
    if (!success && !error) return;
    const t = setTimeout(() => { setSuccess(null); setError(null); }, 3000);
    return () => clearTimeout(t);
  }, [success, error]);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (!imgRef.current) return;
    const rect = imgRef.current.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * 100;
    const y = ((e.clientY - rect.top) / rect.height) * 100;
    dragging.current = true;
    dragStart.current = { x, y };
    setRegion({ x, y, w: 0, h: 0 });
  }, []);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragging.current || !imgRef.current) return;
    const rect = imgRef.current.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * 100;
    const y = ((e.clientY - rect.top) / rect.height) * 100;

    const left = Math.min(dragStart.current.x, x);
    const top = Math.min(dragStart.current.y, y);
    const w = Math.abs(x - dragStart.current.x);
    const h = Math.abs(y - dragStart.current.y);

    setRegion({
      x: Math.max(0, left),
      y: Math.max(0, top),
      w: Math.min(100 - left, w),
      h: Math.min(100 - top, h),
    });
  }, []);

  const handleMouseUp = useCallback(() => {
    dragging.current = false;
    // 最小裁剪区域检查
    setRegion((prev) => {
      if (prev.w < 5 || prev.h < 5) {
        return { x: 20, y: 20, w: 60, h: 60 };
      }
      return prev;
    });
  }, []);

  const handleExecute = useCallback(async () => {
    if (region.w < 5 || region.h < 5) {
      setError('裁剪区域太小，请重新选择');
      return;
    }
    setLoading(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await api.executePreset('focus_crop', {
        nodeId: node.id,
        canvasId: node.canvas_id,
        cropRegion: { x: Math.round(region.x), y: Math.round(region.y), w: Math.round(region.w), h: Math.round(region.h) },
      });
      setSuccess(result.message || '聚焦特写完成');
      setTimeout(() => {
        const { canvas } = useEditorStore.getState();
        if (canvas) {
          useEditorStore.getState().loadCanvas(canvas.id);
        }
      }, 500);
    } catch (err) {
      const msg = err instanceof Error ? err.message : '裁剪失败';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [node, region]);

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 animate-fade-in" onClick={onClose}>
      <div
        ref={overlayRef}
        className="w-[500px] rounded-2xl border border-panel-border panel-solid shadow-soft-lg p-5 animate-slide-down"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 头部 */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Focus size={18} className="text-theme-sub" strokeWidth={1.5} />
            <span className="text-sm font-semibold text-theme-main">聚焦特写</span>
          </div>
          <button
            className="p-1 rounded-full hover:bg-panel-hover text-theme-sub transition-colors"
            onClick={onClose}
          >
            <X size={16} />
          </button>
        </div>

        {/* 提示文字 */}
        <div className="mb-3 text-[10px] text-theme-hint">
          在图片上拖拽选择聚焦区域，选择后将裁剪并放大该区域
        </div>

        {/* 图片裁剪区 */}
        {node.result_url ? (
          <div
            ref={imgRef}
            className="relative w-full max-h-[350px] rounded-xl overflow-hidden border border-panel-border bg-theme-input cursor-crosshair select-none mb-4"
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
          >
            <img
              src={node.result_url}
              alt="原图"
              className="w-full max-h-[350px] object-contain pointer-events-none"
              draggable={false}
            />
            {/* 裁剪框 */}
            <div
              className="absolute border-2 border-accent bg-accent/10 pointer-events-none"
              style={{
                left: `${region.x}%`,
                top: `${region.y}%`,
                width: `${region.w}%`,
                height: `${region.h}%`,
              }}
            >
              {/* 四角标记 */}
              <div className="absolute -top-0.5 -left-0.5 w-2 h-2 border-t-2 border-l-2 border-accent" />
              <div className="absolute -top-0.5 -right-0.5 w-2 h-2 border-t-2 border-r-2 border-accent" />
              <div className="absolute -bottom-0.5 -left-0.5 w-2 h-2 border-b-2 border-l-2 border-accent" />
              <div className="absolute -bottom-0.5 -right-0.5 w-2 h-2 border-b-2 border-r-2 border-accent" />
            </div>
          </div>
        ) : (
          <div className="mb-4 rounded-xl border border-panel-border bg-theme-input p-8 text-center text-[11px] text-theme-hint">
            节点没有已生成的图片
          </div>
        )}

        {/* 区域信息 */}
        <div className="mb-3 flex items-center gap-4 text-[10px] text-theme-sub">
          <span>位置: {Math.round(region.x)}%, {Math.round(region.y)}%</span>
          <span>大小: {Math.round(region.w)}% × {Math.round(region.h)}%</span>
        </div>

        {/* 反馈提示 */}
        {error && (
          <div className="px-3 py-2 mb-3 rounded-xl bg-red-500/10 text-[11px] text-red-400 border border-red-500/20 animate-fade-in">
            {error}
          </div>
        )}
        {success && (
          <div className="px-3 py-2 mb-3 rounded-xl bg-emerald-500/10 text-[11px] text-emerald-400 border border-emerald-500/20 flex items-center gap-1.5 animate-fade-in">
            <Check size={12} className="shrink-0" />
            {success}
          </div>
        )}

        {/* 底部按钮 */}
        <div className="flex gap-2">
          <button
            className="flex-1 h-9 rounded-xl border border-panel-border text-[11px] text-theme-sub hover:bg-panel-hover transition-colors"
            onClick={onClose}
            disabled={loading}
          >
            取消
          </button>
          <button
            className="flex-1 h-9 rounded-xl bg-accent text-[11px] text-white font-medium hover:bg-accent/90 transition-colors flex items-center justify-center gap-1.5 disabled:opacity-50"
            onClick={handleExecute}
            disabled={loading}
          >
            {loading ? (
              <>
                <Loader2 size={13} className="animate-spin" />
                裁剪中...
              </>
            ) : (
              <>
                <Focus size={13} strokeWidth={1.5} />
                执行裁剪
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
