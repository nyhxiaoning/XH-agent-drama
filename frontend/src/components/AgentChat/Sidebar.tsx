/**
 * P4: TokenBadge + AgentSidebar + MessageBubble（重构版）
 * - 侧栏加宽到 340px（展开）/ 44px（折叠）
 * - 消息气泡字号增大到 text-xs (12px)
 * - 头像增大到 28px
 * - 流式进度增强
 */
import { useState, useRef, useEffect, useMemo } from 'react';
import {
  Bot, Send, Loader2, AlertCircle, User, MessageSquare,
  Activity, RefreshCw, Coins, Zap,
} from 'lucide-react';
import { useAgentStore, AGENT_STEPS, type AgentStepKey } from '@/store/agent';
import { api } from '@/utils/api';
import type { AgentMessage, AgentSession } from '@/types';
import { SUB_STEPS, QUICK_FEEDBACK_TAGS } from './constants';

export function TokenBadge() {
  const { session } = useAgentStore();
  const tokens = (session as any)?.token_used ?? 0;
  if (!tokens) return null;
  const cost = (tokens / 1000) * 0.02;
  return (
    <div className="hidden sm:flex items-center gap-1 px-2 py-1 rounded-full bg-canvas-bg border border-panel-border text-xs text-theme-sub">
      <Coins size={11} className="text-indigo-500" />
      <span>~{Number(tokens).toLocaleString()}</span>
      <span className="text-theme-hint">(${cost.toFixed(2)})</span>
    </div>
  );
}

export function AgentSidebar({ compact }: { compact?: boolean }) {
  const { session, currentStep, loading, error, setSession } = useAgentStore();
  const streaming = useAgentStore((s) => s.streaming);
  const streamMessages = useAgentStore((s) => s.streamMessages);
  const currentAgent = useAgentStore((s) => s.currentAgent);
  const streamElapsed = useAgentStore((s) => s.streamElapsed);
  const agentMode = useAgentStore((s) => s.agentMode);
  const oneClickRunning = useAgentStore((s) => s.oneClickRunning);
  const oneClickMessages = useAgentStore((s) => s.oneClickMessages);
  const oneClickProgress = useAgentStore((s) => s.oneClickProgress);
  const oneClickStage = useAgentStore((s) => s.oneClickStage);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [elapsedTick, setElapsedTick] = useState(0);

  const isOneClick = agentMode === 'one-click';
  const activeMessages = isOneClick ? oneClickMessages : streamMessages;
  const activeRunning = isOneClick ? oneClickRunning : streaming;

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [session?.messages, loading, error, currentStep, streamMessages, streaming, oneClickMessages, oneClickRunning]);

  useEffect(() => {
    if (!streaming && !oneClickRunning) return;
    const timer = setInterval(() => setElapsedTick((t) => t + 1), 1000);
    return () => clearInterval(timer);
  }, [streaming, oneClickRunning]);

  const currentSub = (session as any)?.current_sub_step as string | undefined;
  const subSteps = SUB_STEPS[currentStep as AgentStepKey] || [];
  const currentSubLabel = subSteps.find((s) => s.id === currentSub)?.label;
  const quickTags = QUICK_FEEDBACK_TAGS[currentStep as AgentStepKey] || [];

  const streamStats = useMemo(() => {
    if (!activeRunning || activeMessages.length === 0) return null;
    const agentSet = new Set(activeMessages.map((m) => m.agent).filter(Boolean));
    return { count: activeMessages.length, agents: Array.from(agentSet) };
  }, [activeRunning, activeMessages]);

  const handleSend = async (text?: string) => {
    const msg = (text ?? draft).trim();
    if (!msg || !session) return;
    setSubmitting(true);
    setSendError(null);
    const targetStage = session.current_stage || currentStep;
    try {
      const res = await api.shortDramaFeedback(session.id, msg, targetStage);
      if (res.session) {
        setSession(res.session);
      }
      setDraft('');
    } catch (e: any) {
      setSendError(e.message || '反馈发送失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleSend();
    }
  };

  // ── 紧凑模式 ──
  if (compact) {
    return (
      <div className="flex-1 flex flex-col items-center py-3 gap-3 overflow-hidden">
        <div className="w-8 h-8 rounded-full bg-indigo-500/15 text-indigo-500 flex items-center justify-center">
          <Bot size={15} />
        </div>
        {loading && <Loader2 size={14} className="animate-spin text-indigo-500" />}
        {AGENT_STEPS.map((s, idx) => {
          const active = currentStep === s.key;
          const done = AGENT_STEPS.findIndex((x) => x.key === currentStep) > idx;
          return (
            <div
              key={s.key}
              className={`w-2 h-2 rounded-full transition-all ${active ? 'bg-indigo-500 scale-125' : done ? 'bg-success' : 'bg-panel-border'}`}
              title={s.label}
            />
          );
        })}
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* ── Agent 信息区 ── */}
      <div className="p-3.5 border-b border-panel-border/50">
        <div className="flex items-center gap-2.5 mb-2">
          <div className={`w-9 h-9 rounded-xl flex items-center justify-center text-white shadow-soft ${
            isOneClick
              ? 'bg-gradient-to-br from-violet-500 to-indigo-500'
              : 'bg-gradient-to-br from-indigo-500 to-violet-500'
          }`}>
            {isOneClick ? <Zap size={17} /> : <Bot size={17} />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-bold text-theme-main">
              {isOneClick ? '一键极速 Agent' : '星河 Agent'}
            </div>
            <div className="text-xs text-theme-sub truncate">
              {isOneClick && oneClickRunning ? (
                <span className="flex items-center gap-1 text-indigo-500">
                  <Loader2 size={10} className="animate-spin" />
                  {oneClickStage ? `${oneClickStage} 阶段` : '全自动创作中'}
                  <span className="tabular-nums">· {oneClickProgress}%</span>
                </span>
              ) : loading ? (
                <span className="flex items-center gap-1 text-indigo-500">
                  <Loader2 size={10} className="animate-spin" />
                  {currentAgent ? `${currentAgent} 工作中` : currentSubLabel ? `${currentSubLabel} 中` : '处理中'}
                  {streamElapsed > 0 && <span className="tabular-nums">· {streamElapsed}s</span>}
                </span>
              ) : (
                isOneClick ? '等待一键启动' : '等待你的指令'
              )}
            </div>
          </div>
        </div>
        <div className="text-xs text-theme-sub leading-relaxed">
          {isOneClick ? (
            oneClickRunning
              ? `正在自动执行：参数推断 → 剧本创作 → 资产提取 → 资产锁定 → 分镜制作 → 画布创建（${oneClickProgress}%）`
              : '输入一句话灵感，AI 自动完成全流程。生图/生视频需在画布手动确认。'
          ) : (
            <>
              {currentStep === 'start' && '请输入短剧灵感或上传剧本，我会帮你完成从剧本到视频的全流程。'}
              {currentStep === 'planning' && '正在将灵感转化为结构化剧本，你可以随时查看并修改编剧结果。'}
              {currentStep === 'asset' && '请确认需要锁定的角色和场景，锁定后会自动生成概念图。'}
              {currentStep === 'production' && '分镜与视频参数已准备就绪，选择生成范围后开始制作。'}
              {currentStep === 'finalized' && '创作完成！所有节点已同步到画布。'}
            </>
          )}
        </div>
        {/* 一键模式进度条 */}
        {isOneClick && oneClickRunning && (
          <div className="mt-2.5 h-1.5 bg-panel-border/30 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-indigo-500 to-violet-500 rounded-full transition-all duration-700"
              style={{ width: `${oneClickProgress}%` }}
            />
          </div>
        )}
      </div>

      {/* ── 消息流 ── */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3 min-h-0">
        {isOneClick ? (
          <>
            {oneClickMessages.length === 0 && !oneClickRunning && !error && (
              <div className="text-xs text-theme-hint leading-relaxed space-y-2">
                <div className="flex items-center gap-2 text-theme-sub">
                  <Zap size={13} className="text-indigo-500" />
                  <span className="font-medium">一键极速模式</span>
                </div>
                <p>在右侧输入灵感并点击发送，AI 将自动完成从参数到画布的全流程。</p>
                <p className="text-warning/80">生图/生视频需在画布中手动确认触发（涉及费用）。</p>
              </div>
            )}
            {oneClickMessages.map((msg, idx) => (
              <MessageBubble key={`oc${idx}`} msg={msg} />
            ))}
            {oneClickRunning && (
              <div className="flex gap-2">
                <div className="w-7 h-7 rounded-full shrink-0 flex items-center justify-center bg-indigo-500/15 text-indigo-500">
                  <Loader2 size={13} className="animate-spin" />
                </div>
                <div className="glass rounded-2xl rounded-tl-sm px-3.5 py-2.5 text-sm text-theme-main shadow-soft min-w-[200px]">
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="text-xs font-medium text-indigo-500">
                      {oneClickStage ? `${oneClickStage} 进行中` : 'AI 全自动创作中'}
                    </span>
                    <span className="ml-auto text-xs text-theme-hint tabular-nums">{oneClickProgress}%</span>
                  </div>
                  <div className="h-1.5 bg-panel-border/30 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-indigo-500 to-violet-500 rounded-full transition-all duration-700"
                      style={{ width: `${oneClickProgress}%` }}
                    />
                  </div>
                  <div className="text-xs text-theme-hint mt-1.5">
                    已接收 {oneClickMessages.length} 条进度消息
                  </div>
                </div>
              </div>
            )}
          </>
        ) : (
          <>
            {!(session?.messages || []).length && !loading && !error && (
              <div className="text-xs text-theme-hint leading-relaxed space-y-2">
                <div className="flex items-center gap-2 text-theme-sub">
                  <MessageSquare size={13} className="text-indigo-500" />
                  <span className="font-medium">Agent 对话区</span>
                </div>
                <p>我会在这里实时同步每个子 Agent 的运行状态、关键决策和质检反馈。</p>
                <p>右侧为当前步骤的操作面板，完成编辑后点击确认即可进入下一步。</p>
              </div>
            )}
            {(session?.messages || []).map((msg, idx) => (
              <MessageBubble key={`s${idx}`} msg={msg} />
            ))}
            {streaming && streamMessages.length > 0 && streamMessages.map((msg, idx) => (
              <MessageBubble key={`stream${idx}`} msg={msg} />
            ))}
            {/* 流式进度统计 */}
            {streaming && streamStats && (
              <div className="flex items-center gap-2 text-xs text-indigo-500 bg-indigo-500/5 border border-indigo-500/20 rounded-lg px-2.5 py-1.5">
                <Activity size={11} className="animate-pulse" />
                <span>已接收 {streamStats.count} 条进度</span>
                {streamStats.agents.length > 0 && (
                  <span className="text-theme-hint">· {streamStats.agents.join(' → ')}</span>
                )}
              </div>
            )}
            {/* LLM 服务异常检测 */}
            {streaming && (() => {
              const llmError = streamMessages.find(
                (m) => m.content && (
                  m.content.includes('AI 服务请求异常') ||
                  m.content.includes('AI 服务连接失败') ||
                  m.content.includes('AI 服务请求超时') ||
                  m.content.includes('fallback 兜底数据') ||
                  m.content.includes('LLM 服务异常')
                )
              );
              if (!llmError) return null;
              return (
                <div className="flex gap-2">
                  <div className="w-7 h-7 rounded-full shrink-0 flex items-center justify-center bg-warning/15 text-warning">
                    <AlertCircle size={13} />
                  </div>
                  <div className="bg-warning/8 border border-warning/25 rounded-xl rounded-tl-sm px-3.5 py-2.5 text-xs text-theme-main">
                    <div className="font-semibold text-warning mb-1">LLM 服务连接异常</div>
                    <div className="text-xs text-theme-sub leading-relaxed">
                      AI 服务暂时不可用，系统正在自动退避重试。如果持续失败，请检查：
                    </div>
                    <ul className="text-xs text-theme-hint mt-1 space-y-0.5 list-disc list-inside">
                      <li>后端 .env 中 LLM_PROVIDER 和 LLM_MODEL_NAME 配置是否正确</li>
                      <li>API91_API_KEY 或 VOLCENGINE_ARK_API_KEY 是否有效</li>
                      <li>网络是否能正常访问 API 服务地址</li>
                    </ul>
                  </div>
                </div>
              );
            })()}
            {loading && (
              <div className="flex gap-2">
                <div className="w-7 h-7 rounded-full shrink-0 flex items-center justify-center bg-indigo-500/15 text-indigo-500">
                  <Bot size={13} />
                </div>
                <div className="glass rounded-2xl rounded-tl-sm px-3.5 py-2.5 text-sm text-theme-main shadow-soft min-w-[200px]">
                  <div className="flex items-center gap-2 mb-1.5">
                    <Loader2 size={14} className="animate-spin text-indigo-500" />
                    <span className="text-xs font-medium">
                      {currentAgent ? `${currentAgent} 运行中` : currentSubLabel ? `${currentSubLabel} 运行中` : 'AI 正在思考中'}
                    </span>
                    <span className="ml-auto text-xs text-theme-hint tabular-nums">
                      {Math.max(streamElapsed, elapsedTick)}s
                    </span>
                  </div>
                  <div className="h-1.5 bg-panel-border/30 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-indigo-500 to-violet-500 rounded-full transition-all duration-1000"
                      style={{
                        width: `${Math.min(90, Math.max(streamElapsed, elapsedTick) * 2)}%`,
                      }}
                    />
                  </div>
                  <div className="text-xs text-theme-hint mt-1.5">
                    {streamMessages.length > 0
                      ? `已接收 ${streamMessages.length} 条进度消息`
                      : '正在等待 Agent 响应...'}
                  </div>
                </div>
              </div>
            )}
          </>
        )}
        {error && (
          <div className="flex gap-2">
            <div className="w-7 h-7 rounded-full shrink-0 flex items-center justify-center bg-error/15 text-error">
              <AlertCircle size={13} />
            </div>
            <div className="bg-error/8 border border-error/25 rounded-xl rounded-tl-sm px-3.5 py-2.5 text-xs text-error">
              {error}
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* ── 反馈输入区 ── */}
      {session && !isOneClick && (
        <div className="p-3 border-t border-panel-border/50 space-y-2">
          <div className="flex items-center gap-2 text-xs text-theme-hint">
            <Activity size={11} />
            <span>当前阶段：{AGENT_STEPS.find((s) => s.key === currentStep)?.label}</span>
            {session?.retry_count ? (
              <span className="ml-auto flex items-center gap-1 text-warning">
                <RefreshCw size={10} />
                已重试 {session.retry_count} 次
              </span>
            ) : null}
          </div>
          {/* 快捷反馈标签 */}
          {quickTags.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {quickTags.map((tag) => (
                <button
                  key={tag}
                  className="px-2 py-0.5 rounded-md text-xs border border-panel-border/50 bg-panel-bg/50 text-theme-sub hover:border-indigo-500/30 hover:text-indigo-500 transition-all"
                  onClick={() => handleSend(tag)}
                  disabled={loading || submitting}
                >
                  {tag}
                </button>
              ))}
            </div>
          )}
          {sendError && (
            <div className="text-xs text-error bg-error/8 border border-error/20 rounded-lg px-2 py-1">
              {sendError}
            </div>
          )}
          <div className="relative">
            <input
              ref={inputRef}
              type="text"
              className="w-full text-xs bg-theme-input border border-theme-input rounded-xl pl-3 pr-9 py-2 text-theme-main placeholder:text-theme-hint outline-none focus:border-indigo-500/50 transition-all disabled:opacity-50"
              placeholder={
                currentStep === 'planning'
                  ? '输入对编剧结果的反馈... (Ctrl+Enter发送)'
                  : currentStep === 'asset'
                  ? '输入对角色/场景的要求... (Ctrl+Enter发送)'
                  : currentStep === 'production'
                  ? '输入对分镜/视频的要求... (Ctrl+Enter发送)'
                  : '输入反馈或指令... (Ctrl+Enter发送)'
              }
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={loading || submitting}
            />
            <button
              className="absolute right-1 top-1/2 -translate-y-1/2 w-7 h-7 rounded-lg flex items-center justify-center text-indigo-500 hover:bg-indigo-500/10 disabled:opacity-40 transition-colors"
              onClick={() => handleSend()}
              disabled={!draft.trim() || loading || submitting}
            >
              {submitting ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function MessageBubble({ msg }: { msg: AgentMessage }) {
  const isUser = msg.role === 'user';
  const isSystem = msg.role === 'system';
  const time = msg.ts ? new Date(msg.ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '';
  return (
    <div className={`flex gap-2 ${isUser ? 'flex-row-reverse' : ''} animate-fade-up`}>
      <div className={`w-7 h-7 rounded-full shrink-0 flex items-center justify-center ${
        isUser ? 'bg-indigo-500/15 text-indigo-500' : isSystem ? 'bg-warning/15 text-warning' : 'bg-violet-500/15 text-violet-500'
      }`}>
        {isUser ? <User size={13} /> : isSystem ? <AlertCircle size={13} /> : <Bot size={13} />}
      </div>
      <div className={`max-w-[85%] rounded-2xl px-3 py-2 text-xs leading-relaxed shadow-soft ${
        isUser
          ? 'bg-indigo-500/10 text-theme-main rounded-tr-sm border border-indigo-500/15'
          : isSystem
          ? 'bg-warning/8 text-theme-main rounded-tl-sm border border-warning/20'
          : 'glass text-theme-main rounded-tl-sm'
      }`}>
        <div className="flex items-center justify-between gap-2 mb-0.5">
          {msg.agent && <div className="text-xs text-indigo-500 font-medium">{msg.agent}</div>}
          {time && <div className="text-[10px] text-theme-hint">{time}</div>}
        </div>
        <div className="whitespace-pre-line">{msg.content}</div>
      </div>
    </div>
  );
}
