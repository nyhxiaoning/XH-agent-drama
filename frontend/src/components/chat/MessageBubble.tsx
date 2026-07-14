/**
 * MessageBubble - 通用消息气泡组件
 *
 * 从 AgentChat / SkillChat 中提取的公共消息渲染逻辑。
 * 支持 user / progress / error / system 四种基础角色。
 *
 * 对于 assistant 角色（含结构化卡片），各组件可自行渲染，
 * 或通过 renderAssistant 回调自定义。
 */
import { useState } from 'react';
import {
  Brain, User, AlertCircle, Copy, Check, RotateCcw,
  type LucideIcon,
} from 'lucide-react';
import type { ChatMessage } from './types';
import { TypingIndicator } from './TypingIndicator';

export interface MessageBubbleProps {
  msg: ChatMessage;
  gradient: string;
  /** 进度消息的图标（默认 Brain） */
  progressIcon?: LucideIcon;
  /** 进度消息的名称标签 */
  progressLabel?: string;
  /** 是否显示时间戳 */
  showTimestamp?: boolean;
  /** 复制回调 */
  onCopy?: (text: string) => void;
  /** 重试回调（错误消息显示） */
  onRetry?: () => void;
  /** 自定义 assistant 消息渲染 */
  renderAssistant?: (msg: ChatMessage, copied: boolean, handleCopy: () => void) => React.ReactNode;
}

export function MessageBubble({
  msg,
  gradient,
  progressIcon: ProgressIcon = Brain,
  progressLabel,
  showTimestamp = false,
  onCopy,
  onRetry,
  renderAssistant,
}: MessageBubbleProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    const text = msg.content;
    if (onCopy) {
      onCopy(text);
    } else {
      navigator.clipboard?.writeText(text);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const formatTs = (ts: number) => {
    const d = new Date(ts);
    const h = d.getHours().toString().padStart(2, '0');
    const m = d.getMinutes().toString().padStart(2, '0');
    return `${h}:${m}`;
  };

  // ── 用户消息 ──
  if (msg.role === 'user') {
    return (
      <div className="flex justify-end items-start gap-2.5 animate-fade-up">
        <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-teal-600/8 border border-teal-600/15 px-4 py-2.5">
          <div className="text-sm text-theme-main whitespace-pre-wrap break-words leading-relaxed">{msg.content}</div>
          {showTimestamp && (
            <div className="text-[10px] text-theme-hint mt-1 text-right">{formatTs(msg.timestamp)}</div>
          )}
        </div>
        <div className="w-8 h-8 rounded-full shrink-0 flex items-center justify-center bg-teal-600/10 border border-teal-600/20">
          <User size={15} className="text-teal-600" />
        </div>
      </div>
    );
  }

  // ── 进度消息 ──
  if (msg.role === 'progress') {
    return (
      <div className="flex justify-start items-start gap-2.5 animate-fade-in">
        <div className={`w-8 h-8 rounded-full shrink-0 flex items-center justify-center bg-gradient-to-br ${gradient} shadow-soft`}>
          <ProgressIcon size={15} className="text-white animate-pulse" />
        </div>
        <div className="rounded-2xl rounded-tl-sm bg-panel-bg border border-panel-border px-4 py-2.5 shadow-soft max-w-[80%]">
          {progressLabel && (
            <div className="flex items-center gap-1.5 text-xs text-teal-600 mb-0.5">
              <ProgressIcon size={11} />
              <span className="font-medium">{progressLabel}</span>
              {showTimestamp && <span className="text-theme-hint">· {formatTs(msg.timestamp)}</span>}
            </div>
          )}
          <div className="flex items-center gap-2.5">
            {!progressLabel && <TypingIndicator />}
            <span className="text-sm text-theme-sub whitespace-pre-wrap break-words leading-relaxed">{msg.content}</span>
          </div>
        </div>
      </div>
    );
  }

  // ── 错误消息 ──
  if (msg.role === 'error') {
    return (
      <div className="flex justify-start items-start gap-2.5 animate-fade-up">
        <div className={`w-8 h-8 rounded-full shrink-0 flex items-center justify-center bg-gradient-to-br ${gradient} shadow-soft`}>
          <AlertCircle size={15} className="text-white" />
        </div>
        <div className="max-w-[75%] rounded-2xl rounded-tl-sm bg-error/8 border border-error/25 px-4 py-3">
          <div className="text-xs text-error font-semibold mb-1">执行失败</div>
          <div className="text-sm text-error/80 whitespace-pre-wrap break-words leading-relaxed">{msg.content}</div>
          {onRetry && (
            <button
              onClick={onRetry}
              className="mt-2 text-xs text-teal-600 hover:underline flex items-center gap-1 font-medium"
            >
              <RotateCcw size={12} /> 重试
            </button>
          )}
        </div>
      </div>
    );
  }

  // ── 系统消息 ──
  if (msg.role === 'system') {
    return (
      <div className="flex justify-center animate-fade-in">
        <div className="text-xs text-theme-hint bg-panel-bg border border-panel-border/50 rounded-full px-3 py-1">
          {msg.content}
        </div>
      </div>
    );
  }

  // ── AI 回复消息 ──
  // 如果提供了自定义渲染函数，使用它
  if (renderAssistant) {
    return <>{renderAssistant(msg, copied, handleCopy)}</>;
  }

  // 默认 AI 回复渲染
  return (
    <div className="flex justify-start items-start gap-2.5 animate-fade-up">
      <div className={`w-8 h-8 rounded-full shrink-0 flex items-center justify-center bg-gradient-to-br ${gradient} shadow-soft`}>
        <Brain size={15} className="text-white" />
      </div>
      <div className="max-w-[85%] rounded-2xl rounded-tl-sm bg-panel-bg border border-panel-border shadow-soft overflow-hidden">
        <div className="flex items-center gap-1.5 px-4 pt-3 pb-2 text-xs text-teal-600">
          <Brain size={12} />
          <span className="font-medium">智能体调度完成</span>
          {showTimestamp && <span className="text-theme-hint ml-auto">{formatTs(msg.timestamp)}</span>}
        </div>
        <div className="px-4 pb-3 space-y-2.5">
          <div className="rounded-xl bg-canvas-bg/50 border border-panel-border/40 p-3 max-h-[500px] overflow-y-auto">
            <div className="chat-content">{msg.content}</div>
          </div>
          <div className="flex items-center gap-3 pt-1">
            <button
              onClick={handleCopy}
              className="text-xs text-theme-sub hover:text-teal-600 flex items-center gap-1 transition-colors"
            >
              {copied ? <Check size={12} className="text-success" /> : <Copy size={12} />}
              {copied ? '已复制' : '复制'}
            </button>
            {onRetry && (
              <button
                onClick={onRetry}
                className="text-xs text-theme-sub hover:text-teal-600 flex items-center gap-1 transition-colors"
              >
                <RotateCcw size={12} />
                重新生成
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
