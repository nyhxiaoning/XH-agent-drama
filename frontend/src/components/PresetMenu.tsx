import { useState, useRef, useEffect, useCallback } from 'react';
import { Sparkles, Loader2, X, Check } from 'lucide-react';
import { getAvailablePresets, type PresetFeature } from '@/utils/presetFeatures';
import { api } from '@/utils/api';
import { useEditorStore } from '@/store/editor';
import type { CanvasNode } from '@/types';
import { GridSplitOverlay } from './GridSplitOverlay';
import { CropOverlay } from './CropOverlay';

interface PresetMenuProps {
  node: CanvasNode;
}

export function PresetMenu({ node }: PresetMenuProps) {
  const [open, setOpen] = useState(false);
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [overlay, setOverlay] = useState<'grid_split' | 'focus_crop' | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const hasResult = !!node.result_url && node.status === 'success';
  const presets = getAvailablePresets(node.node_type, hasResult);

  // 关闭外部点击
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
        setError(null);
        setSuccess(null);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  // 自动清除成功/错误提示
  useEffect(() => {
    if (!success && !error) return;
    const t = setTimeout(() => { setSuccess(null); setError(null); }, 3000);
    return () => clearTimeout(t);
  }, [success, error]);

  const handleExecute = useCallback(async (preset: PresetFeature) => {
    // ── 宫格切分：打开 overlay 组件 ──
    if (preset.id === 'grid_split') {
      setOverlay('grid_split');
      setOpen(false);
      return;
    }

    // ── 聚焦特写：打开 overlay 组件 ──
    if (preset.id === 'focus_crop') {
      setOverlay('focus_crop');
      setOpen(false);
      return;
    }

    // ── 后端处理的功能 ──
    setLoadingId(preset.id);
    setError(null);
    setSuccess(null);
    try {
      const result = await api.executePreset(preset.id, {
        nodeId: node.id,
        canvasId: node.canvas_id,
        prompt: node.prompt,
        style: node.style,
        config: (node.config || {}) as Record<string, unknown>,
      });

      setSuccess(result.message || `${preset.label} 已提交`);
      // 刷新画布以显示新创建的下游节点和连线
      setTimeout(() => {
        const { canvas } = useEditorStore.getState();
        if (canvas) {
          useEditorStore.getState().loadCanvas(canvas.id);
        }
      }, 300);
      setTimeout(() => setOpen(false), 800);
    } catch (err) {
      const msg = err instanceof Error ? err.message : '执行失败';
      setError(msg);
    } finally {
      setLoadingId(null);
    }
  }, [node]);

  // 如果没有可用预设，不渲染按钮
  if (presets.length === 0) return null;

  return (
    <>
      <div className="relative" ref={menuRef}>
        <button
          className="h-9 min-w-[76px] px-3 rounded-r-full bg-transparent text-[11px] text-theme-main flex items-center gap-1.5 transition-all duration-150 hover:bg-panel-hover focus:outline-none cursor-pointer"
          onClick={() => setOpen((v) => !v)}
          title="预设功能"
        >
          <Sparkles size={13} className="text-theme-sub" />
          <span className="truncate max-w-[60px]">预设</span>
        </button>

        {open && (
          <div className="absolute left-0 bottom-full mb-2 w-[320px] max-h-[380px] overflow-y-auto rounded-2xl border border-panel-border shadow-soft-lg z-50 p-2 panel-solid animate-slide-down">
            {/* 头部 */}
            <div className="flex items-center justify-between px-2 py-1.5 mb-1">
              <span className="text-[10px] text-theme-hint font-semibold uppercase tracking-wider flex items-center gap-1.5">
                <Sparkles size={11} className="text-theme-sub" />
                预设功能
              </span>
              <button
                className="p-0.5 rounded-full hover:bg-panel-hover text-theme-sub transition-colors"
                onClick={() => { setOpen(false); setError(null); setSuccess(null); }}
              >
                <X size={12} />
              </button>
            </div>

            {/* 反馈提示 */}
            {error && (
              <div className="px-2.5 py-2 mb-1.5 rounded-xl bg-red-500/10 text-[10px] text-red-400 border border-red-500/20 animate-fade-in">
                {error}
              </div>
            )}
            {success && (
              <div className="px-2.5 py-2 mb-1.5 rounded-xl bg-emerald-500/10 text-[10px] text-emerald-400 border border-emerald-500/20 flex items-center gap-1.5 animate-fade-in">
                <Check size={11} className="shrink-0" />
                {success}
              </div>
            )}

            {/* 功能列表 */}
            <div className="space-y-0.5">
              {presets.map((preset) => {
                const Icon = preset.icon;
                const isLoading = loadingId === preset.id;
                return (
                  <button
                    key={preset.id}
                    disabled={!!loadingId}
                    className="w-full flex items-center gap-2.5 px-2.5 py-2.5 rounded-xl text-left transition-all duration-150 hover:bg-panel-hover disabled:opacity-50 group"
                    onClick={() => handleExecute(preset)}
                  >
                    <div className="w-8 h-8 rounded-lg bg-theme-input border border-panel-border flex items-center justify-center shrink-0 group-hover:border-accent/40 transition-colors duration-150">
                      {isLoading ? (
                        <Loader2 size={15} className="animate-spin text-theme-sub" />
                      ) : (
                        <Icon size={15} className="text-theme-sub transition-transform duration-200 group-hover:scale-110" strokeWidth={1.5} />
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-[11px] font-medium text-theme-main group-hover:text-accent transition-colors duration-150">
                        {preset.label}
                      </div>
                      <div className="text-[9px] text-theme-sub truncate leading-tight mt-0.5">
                        {preset.desc}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>

            {/* 底部提示 */}
            <div className="px-2 py-1.5 mt-1 border-t border-panel-border/30 text-[8px] text-theme-hint text-center">
              点击执行预设功能
            </div>
          </div>
        )}
      </div>

      {/* 宫格切分 overlay */}
      {overlay === 'grid_split' && (
        <GridSplitOverlay node={node} onClose={() => setOverlay(null)} />
      )}

      {/* 聚焦特写 overlay */}
      {overlay === 'focus_crop' && (
        <CropOverlay node={node} onClose={() => setOverlay(null)} />
      )}
    </>
  );
}
