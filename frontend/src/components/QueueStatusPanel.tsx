/**
 * #19 生成队列状态面板
 *
 * 展示当前图片/视频生成队列的实时状态：
 * - 待处理 / 运行中 / 已完成 / 失败 数量
 * - 运行中任务详情（节点 ID、类型、进度）
 * - 待处理任务优先级排序
 * - 批量取消当前画布的所有任务
 *
 * 使用方式：
 * <QueueStatusPanel canvasId="xxx" />  // 指定画布
 * <QueueStatusPanel />                  // 全局队列
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Loader2, CheckCircle, AlertCircle, XCircle, ListChecks,
  Image as ImageIcon, Video, Ban, RefreshCw, Clock,
} from 'lucide-react';
import { api } from '@/utils/api';

interface QueueStatus {
  total: number;
  pending: number;
  running: number;
  success: number;
  failed: number;
  cancelled: number;
  max_concurrent: number;
  pending_details: Array<{
    task_id: string;
    node_id: string;
    task_type: string;
    priority: number;
    created_at: string;
  }>;
  running_details: Array<{
    task_id: string;
    node_id: string;
    task_type: string;
    started_at: string | null;
    progress: number;
  }>;
}

interface QueueStatusPanelProps {
  canvasId?: string;
  /** 自动刷新间隔（毫秒），默认 3000 */
  interval?: number;
  /** 紧凑模式（仅显示一行摘要） */
  compact?: boolean;
}

const TASK_TYPE_LABELS: Record<string, { label: string; icon: typeof ImageIcon }> = {
  generate_image: { label: '图片生成', icon: ImageIcon },
  generate_video: { label: '视频生成', icon: Video },
};

export function QueueStatusPanel({ canvasId, interval = 3000, compact = false }: QueueStatusPanelProps) {
  const [status, setStatus] = useState<QueueStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await api.getQueueStatus(canvasId);
      setStatus(data);
      setError('');
    } catch (e: any) {
      setError(e?.message || '获取队列状态失败');
    }
  }, [canvasId]);

  // 定时轮询
  useEffect(() => {
    fetchStatus();
    timerRef.current = setInterval(fetchStatus, interval);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [fetchStatus, interval]);

  const handleCancelAll = async () => {
    if (!canvasId) return;
    if (!window.confirm('确定要取消当前画布的所有待处理和运行中任务吗？')) return;
    setCancelling(true);
    try {
      const result = await api.cancelTasksByCanvas(canvasId);
      // 刷新状态
      await fetchStatus();
      console.info('[QueueStatus] 已取消任务:', result.cancelled_count);
    } catch (e: any) {
      setError(e?.message || '取消任务失败');
    } finally {
      setCancelling(false);
    }
  };

  const handleRefresh = () => {
    setLoading(true);
    fetchStatus().finally(() => setLoading(false));
  };

  if (!status) {
    return (
      <div className="flex items-center gap-2 text-xs text-theme-hint px-3 py-2">
        <Loader2 size={12} className="animate-spin" />
        加载队列状态...
      </div>
    );
  }

  const hasActive = status.pending > 0 || status.running > 0;
  const hasAny = status.total > 0;

  // 紧凑模式：仅显示一行摘要
  if (compact) {
    if (!hasAny) return null;
    return (
      <button
        onClick={() => setExpanded(v => !v)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-xl glass border border-panel-border text-xs hover:bg-panel-hover transition-colors"
      >
        {hasActive ? (
          <Loader2 size={12} className="animate-spin text-teal-600" />
        ) : (
          <CheckCircle size={12} className="text-success" />
        )}
        <span className="text-theme-sub">
          队列: {status.running} 运行 / {status.pending} 等待
          {status.failed > 0 && <span className="text-error ml-1">/ {status.failed} 失败</span>}
        </span>
        {hasActive && canvasId && (
          <span
            onClick={(e) => { e.stopPropagation(); handleCancelAll(); }}
            className="text-error hover:underline ml-1"
          >
            全部取消
          </span>
        )}
      </button>
    );
  }

  return (
    <div className="glass rounded-2xl border border-panel-border shadow-soft overflow-hidden">
      {/* 头部 */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-panel-border/50">
        <div className="flex items-center gap-2">
          <ListChecks size={14} className="text-teal-600" />
          <span className="text-sm font-semibold text-theme-main">生成队列</span>
          {hasActive && (
            <span className="flex items-center gap-1 text-[10px] text-teal-600 font-medium px-1.5 py-0.5 rounded-full bg-teal-600/10">
              <span className="w-1.5 h-1.5 rounded-full bg-teal-600 animate-pulse" />
              实时
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={handleRefresh}
            disabled={loading}
            className="w-7 h-7 rounded-lg flex items-center justify-center text-theme-sub hover:text-theme-main hover:bg-panel-hover transition-colors disabled:opacity-50"
            title="刷新"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          </button>
          {hasActive && canvasId && (
            <button
              onClick={handleCancelAll}
              disabled={cancelling}
              className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] text-error hover:bg-error/10 transition-colors disabled:opacity-50"
              title="取消所有任务"
            >
              {cancelling ? <Loader2 size={10} className="animate-spin" /> : <Ban size={10} />}
              全部取消
            </button>
          )}
        </div>
      </div>

      {/* 统计数字 */}
      <div className="grid grid-cols-5 gap-1 px-4 py-3">
        <StatBlock label="总数" value={status.total} color="text-theme-main" />
        <StatBlock label="运行中" value={status.running} color="text-teal-600" icon={<Loader2 size={10} className="animate-spin" />} />
        <StatBlock label="等待中" value={status.pending} color="text-amber-500" icon={<Clock size={10} />} />
        <StatBlock label="已完成" value={status.success} color="text-success" icon={<CheckCircle size={10} />} />
        <StatBlock label="失败" value={status.failed} color="text-error" icon={<AlertCircle size={10} />} />
      </div>

      {/* 运行中任务详情 */}
      {status.running_details.length > 0 && (
        <div className="px-4 pb-2">
          <div className="text-[10px] font-semibold text-theme-sub mb-1.5">运行中</div>
          <div className="space-y-1">
            {status.running_details.map((t) => {
              const info = TASK_TYPE_LABELS[t.task_type] || { label: t.task_type, icon: ImageIcon };
              const Icon = info.icon;
              return (
                <div key={t.task_id} className="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-canvas-bg/50 border border-panel-border/30">
                  <Icon size={12} className="text-teal-600 shrink-0" />
                  <span className="text-[11px] text-theme-main flex-1 min-w-0 truncate">{info.label}</span>
                  <span className="text-[10px] text-theme-hint tabular-nums">{t.node_id.slice(0, 8)}</span>
                  <div className="w-16 h-1 rounded-full bg-panel-border/40 overflow-hidden shrink-0">
                    <div className="h-full bg-teal-600 rounded-full transition-all" style={{ width: `${t.progress}%` }} />
                  </div>
                  <span className="text-[10px] text-theme-sub tabular-nums w-8 text-right">{t.progress}%</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 待处理任务详情 */}
      {status.pending_details.length > 0 && (
        <div className="px-4 pb-3">
          <div className="text-[10px] font-semibold text-theme-sub mb-1.5">等待中 ({status.pending_details.length})</div>
          <div className="space-y-0.5 max-h-[120px] overflow-y-auto">
            {status.pending_details.slice(0, 10).map((t) => {
              const info = TASK_TYPE_LABELS[t.task_type] || { label: t.task_type, icon: ImageIcon };
              const Icon = info.icon;
              return (
                <div key={t.task_id} className="flex items-center gap-2 px-2 py-1 rounded-lg hover:bg-panel-hover/50 transition-colors">
                  <Icon size={11} className="text-theme-hint shrink-0" />
                  <span className="text-[10px] text-theme-sub flex-1 min-w-0 truncate">{info.label}</span>
                  <span className="text-[9px] text-theme-hint tabular-nums">{t.node_id.slice(0, 8)}</span>
                  <span className="text-[9px] px-1 py-0.5 rounded-full bg-panel-border/30 text-theme-hint shrink-0">
                    P{t.priority}
                  </span>
                </div>
              );
            })}
            {status.pending_details.length > 10 && (
              <div className="text-[10px] text-theme-hint text-center pt-0.5">
                还有 {status.pending_details.length - 10} 个任务...
              </div>
            )}
          </div>
        </div>
      )}

      {/* 空状态 */}
      {!hasAny && (
        <div className="px-4 py-6 text-center">
          <CheckCircle size={24} className="text-success/40 mx-auto mb-1.5" />
          <div className="text-xs text-theme-hint">队列为空，暂无生成任务</div>
        </div>
      )}

      {/* 失败任务提示 */}
      {status.failed > 0 && (
        <div className="px-4 py-2 border-t border-panel-border/30 bg-error/5">
          <div className="flex items-center gap-1.5 text-[10px] text-error">
            <AlertCircle size={11} />
            <span>{status.failed} 个任务失败，请在画布中查看详情并重试</span>
          </div>
        </div>
      )}

      {/* 错误提示 */}
      {error && (
        <div className="px-4 py-2 border-t border-panel-border/30 bg-error/5">
          <div className="flex items-center gap-1.5 text-[10px] text-error">
            <XCircle size={11} />
            <span>{error}</span>
          </div>
        </div>
      )}
    </div>
  );
}

function StatBlock({
  label, value, color, icon,
}: {
  label: string;
  value: number;
  color: string;
  icon?: React.ReactNode;
}) {
  return (
    <div className="text-center">
      <div className={`flex items-center justify-center gap-0.5 text-lg font-bold tabular-nums ${color}`}>
        {icon}
        {value}
      </div>
      <div className="text-[10px] text-theme-hint mt-0.5">{label}</div>
    </div>
  );
}
