/**
 * 宫格切分交互组件
 * 当节点 config.preset_grid_split === true 时显示，
 * 让用户选择切分行列数，然后调用后端 API 执行切分。
 */
import { useState, useRef, useEffect, useCallback } from 'react';
import { Grid3x3, Loader2, X, Check } from 'lucide-react';
import { api } from '@/utils/api';
import { useEditorStore } from '@/store/editor';
import type { CanvasNode } from '@/types';

interface GridSplitOverlayProps {
  node: CanvasNode;
  onClose: () => void;
}

const PRESETS = [
  { rows: 2, cols: 2, label: '2×2' },
  { rows: 3, cols: 3, label: '3×3' },
  { rows: 4, cols: 4, label: '4×4' },
  { rows: 2, cols: 3, label: '2×3' },
  { rows: 3, cols: 4, label: '3×4' },
];

export function GridSplitOverlay({ node, onClose }: GridSplitOverlayProps) {
  const [selected, setSelected] = useState({ rows: 3, cols: 3 });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const overlayRef = useRef<HTMLDivElement>(null);

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

  const handleExecute = useCallback(async () => {
    setLoading(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await api.executePreset('grid_split', {
        nodeId: node.id,
        canvasId: node.canvas_id,
        gridRows: selected.rows,
        gridCols: selected.cols,
      });
      setSuccess(result.message || `已切分为 ${selected.rows}×${selected.cols}`);
      // 刷新画布以显示新节点
      setTimeout(() => {
        const { canvas } = useEditorStore.getState();
        if (canvas) {
          useEditorStore.getState().loadCanvas(canvas.id);
        }
      }, 500);
    } catch (err) {
      const msg = err instanceof Error ? err.message : '切分失败';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [node, selected]);

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 animate-fade-in" onClick={onClose}>
      <div
        ref={overlayRef}
        className="w-[400px] rounded-2xl border border-panel-border panel-solid shadow-soft-lg p-5 animate-slide-down"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 头部 */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Grid3x3 size={18} className="text-theme-sub" strokeWidth={1.5} />
            <span className="text-sm font-semibold text-theme-main">宫格切分</span>
          </div>
          <button
            className="p-1 rounded-full hover:bg-panel-hover text-theme-sub transition-colors"
            onClick={onClose}
          >
            <X size={16} />
          </button>
        </div>

        {/* 预览图 */}
        {node.result_url && (
          <div className="mb-4 rounded-xl overflow-hidden border border-panel-border bg-theme-input">
            <img
              src={node.result_url}
              alt="原图"
              className="w-full max-h-[200px] object-contain"
            />
          </div>
        )}

        {/* 切分预设选择 */}
        <div className="mb-4">
          <div className="text-[10px] text-theme-hint font-semibold uppercase tracking-wider mb-2">
            选择切分方式
          </div>
          <div className="grid grid-cols-5 gap-2">
            {PRESETS.map((preset) => {
              const isActive = selected.rows === preset.rows && selected.cols === preset.cols;
              return (
                <button
                  key={preset.label}
                  className={`h-10 rounded-lg border text-[11px] font-medium transition-all duration-150 ${
                    isActive
                      ? 'border-accent bg-accent/10 text-accent'
                      : 'border-panel-border bg-theme-input text-theme-sub hover:bg-panel-hover'
                  }`}
                  onClick={() => setSelected({ rows: preset.rows, cols: preset.cols })}
                >
                  {preset.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* 网格预览 */}
        <div className="mb-4 flex justify-center">
          <div
            className="grid gap-0.5 rounded-lg overflow-hidden border border-panel-border"
            style={{
              gridTemplateColumns: `repeat(${selected.cols}, 1fr)`,
              width: '120px',
              height: '120px',
            }}
          >
            {Array.from({ length: selected.rows * selected.cols }).map((_, i) => (
              <div
                key={i}
                className="bg-theme-input hover:bg-accent/20 transition-colors duration-150"
              />
            ))}
          </div>
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
                切分中...
              </>
            ) : (
              <>
                <Grid3x3 size={13} strokeWidth={1.5} />
                执行切分
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
