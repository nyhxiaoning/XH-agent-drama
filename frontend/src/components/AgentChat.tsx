/**
 * AgentChat - 对话式重构版
 *
 * 布局参考: ChatGPT / SkillChat
 * - 左侧历史会话侧栏（localStorage 持久化）
 * - 顶部品牌渐变Header
 * - 居中对话流，空状态有引导卡片
 * - 大脑流式推送6步进度（SSE 实时显示）
 * - 剧本/资产/分镜/视频 结构化展示卡片嵌入对话流
 * - 底部输入区带模式切换、文件上传
 *
 * 后端不变：仍使用 shortDramaStepStream SSE 接口
 */
import { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Send, Sparkles, Loader2, Copy, Check, RotateCcw,
  Brain, User, Plus, MessageSquare, Trash2,
  PanelLeftClose, PanelLeftOpen, Upload, BookText, BookOpen,
  Clapperboard, CheckCircle, AlertCircle, Lock, Image as ImageIcon,
  Film, LayoutGrid, ChevronDown, ChevronUp, Zap, type LucideIcon,
} from 'lucide-react';
import { useAgentStore } from '@/store/agent';
import { useEditorStore } from '@/store/editor';
import type { AgentSession } from '@/types';
import { GLOBAL_PARAM_DEFINITIONS, DRAMA_MAX_RETRIES } from './AgentChat/constants';
import { OneClickPanel } from './AgentChat/panels/OneClickPanel';
// #15 实时步骤指示器
import { StreamingStatusBar } from './AgentChat/StreamingStatusBar';
// #20 主步骤进度条
import { Stepper } from './AgentChat/Stepper';
// #12 公共组件去重
import type { ChatMessage } from '@/components/chat/types';
import { useAutoScroll, TypingIndicator } from '@/components/chat';

// ─── 类型 ────────────────────────────────────────────

// #12 使用公共 ChatMessage 类型，本地别名保持兼容
type AgentChatMessage = ChatMessage;

interface AgentChatProps {
  docked?: boolean;
  page?: boolean;
  /** docked 模式下点击关闭按钮的回调 */
  onClose?: () => void;
}

// ─── 常量 ────────────────────────────────────────────

const GRADIENT = 'from-teal-600 to-emerald-500';

const AGENT_LABELS: Record<string, { name: string; icon: LucideIcon }> = {
  script_planner: { name: '剧本架构师', icon: BookOpen },
  screenwriter: { name: '文学编剧', icon: BookText },
  character_designer: { name: '角色设计师', icon: User },
  scene_prop_designer: { name: '场景设计师', icon: LayoutGrid },
  storyboard_director: { name: '分镜导演', icon: Clapperboard },
  video_composer: { name: '视频作曲', icon: Film },
  director_brain: { name: '总导演智能体', icon: Brain },
  asset_parallel: { name: '资产调度', icon: LayoutGrid },
  system: { name: '系统', icon: AlertCircle },
};

// ─── 辅助函数 ────────────────────────────────────────

function getAgentLabel(agent?: string): { name: string; icon: LucideIcon } {
  if (!agent) return { name: '智能体', icon: Brain };
  return AGENT_LABELS[agent] || { name: agent, icon: Brain };
}

function formatTime(ts: number): string {
  const d = new Date(ts);
  const h = d.getHours().toString().padStart(2, '0');
  const m = d.getMinutes().toString().padStart(2, '0');
  return `${h}:${m}`;
}

// ─── 主组件 ──────────────────────────────────────────

export function AgentChat({ docked, page, onClose }: AgentChatProps) {
  const navigate = useNavigate();
  const loadCanvas = useEditorStore((s) => s.loadCanvas);

  const {
    session, loading, error,
    finalizedCanvasId, currentStep,
    selectedChars, selectedScenes,
    start, runStep, finalize, reset, skipStep,
    toggleChar, toggleScene, selectAllAssets, lockAssets,
    globalParams, setGlobalParam, confirmParameters,
    parameterPending,
    streamMessages, streaming, currentAgent,
    agentMode, modeChosen, backToAgentSelector,
    goToStep,
  } = useAgentStore();

  // 本地消息列表
  const [messages, setMessages] = useState<AgentChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [mode, setMode] = useState<'inspiration' | 'script' | 'novel'>('inspiration');
  const [scriptText, setScriptText] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(!docked);
  // docked 模式不再有折叠态，由外部控制显隐

  // 历史会话列表（localStorage）
  const [history, setHistory] = useState<{ id: string; title: string; ts: number }[]>([]);

  const scrollRef = useAutoScroll([messages, loading]);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const processedStreamIds = useRef<Set<string>>(new Set());
  const renderedCardTypes = useRef<Set<string>>(new Set());

  // ─── 加载历史 ───────────────────────────────────────
  useEffect(() => {
    try {
      const raw = localStorage.getItem('agentHistory');
      if (raw) setHistory(JSON.parse(raw));
    } catch {}
    const sid = localStorage.getItem('agentSessionId');
    if (sid) {
      useAgentStore.getState().hydrateSession(sid);
    }
  }, []);

  // ─── 滚动到底部 ─────────────────────────────────────
  // #12 使用公共 useAutoScroll，已在上文初始化

  // ─── SSE 流消息 → 聊天消息 ──────────────────────────
  useEffect(() => {
    if (!streaming) return;
    for (const msg of streamMessages) {
      const msgId = `stream-${msg.ts}-${msg.agent || ''}-${msg.content?.slice(0, 20)}`;
      if (processedStreamIds.current.has(msgId)) continue;
      processedStreamIds.current.add(msgId);

      const { name, icon: AgentIcon } = getAgentLabel(msg.agent);
      setMessages((prev) => [...prev, {
        id: msgId,
        role: 'progress',
        content: msg.content,
        agent: msg.agent,
        step: msg.step,
        timestamp: (msg.ts || Date.now() / 1000) * 1000,
      }]);
    }
  }, [streamMessages, streaming]);

  // ─── 检测阶段完成 → 渲染结果卡片 ────────────────────
  // 使用 Set 去重，不依赖 stage 字符串比较
  useEffect(() => {
    if (!session || streaming) return;

    // planning 完成：有剧本数据且未渲染过
    if ((session.full_script || session.screenwriter) && !renderedCardTypes.current.has('planning_result')) {
      renderedCardTypes.current.add('planning_result');
      setMessages((prev) => [...prev, {
        id: `card-planning-${Date.now()}`,
        role: 'assistant',
        content: '前期策划完成',
        cardType: 'planning_result',
        rawData: session,
        timestamp: Date.now(),
      }]);
      return;
    }

    // asset 完成：有资产数据且未渲染过
    if ((session.character_assets || session.scene_assets || session.character || session.scene || session.assets) &&
        !renderedCardTypes.current.has('asset_result') &&
        (session.status === 'assets_ready' || (!session.locked_assets?.length && !session.status?.startsWith('running_')))) {
      renderedCardTypes.current.add('asset_result');
      setMessages((prev) => [...prev, {
        id: `card-asset-${Date.now()}`,
        role: 'assistant',
        content: '资产设定完成',
        cardType: 'asset_result',
        rawData: session,
        timestamp: Date.now(),
      }]);
      return;
    }

    // production 完成：有分镜/视频数据且未渲染过
    if ((session.video_plan || session.videos) && !renderedCardTypes.current.has('production_result')) {
      renderedCardTypes.current.add('production_result');
      setMessages((prev) => [...prev, {
        id: `card-production-${Date.now()}`,
        role: 'assistant',
        content: '拍摄制作完成',
        cardType: 'production_result',
        rawData: session,
        timestamp: Date.now(),
      }]);
      return;
    }
  }, [session, streaming]);

  // ─── parameter_pending → 参数确认卡片 ───────────────
  useEffect(() => {
    if (session?.parameter_pending && parameterPending) {
      // 检查是否已经有参数卡片
      const hasParamCard = messages.some(m => m.cardType === 'parameter_pending');
      if (!hasParamCard) {
        setMessages((prev) => [...prev, {
          id: `card-param-${Date.now()}`,
          role: 'assistant',
          content: '请确认全局创作参数',
          cardType: 'parameter_pending',
          rawData: session,
          timestamp: Date.now(),
        }]);
      }
    }
  }, [session?.parameter_pending, parameterPending]);

  // ─── finalized ──────────────────────────────────────
  useEffect(() => {
    if (session?.status === 'finalized' && finalizedCanvasId) {
      const hasFinalCard = messages.some(m => m.cardType === 'finalized_result');
      if (!hasFinalCard) {
        setMessages((prev) => [...prev, {
          id: `card-final-${Date.now()}`,
          role: 'assistant',
          content: '创作完成！画布已创建',
          cardType: 'finalized_result',
          rawData: { canvasId: finalizedCanvasId },
          timestamp: Date.now(),
        }]);
      }
    }
  }, [session?.status, finalizedCanvasId]);

  // ─── error ──────────────────────────────────────────
  useEffect(() => {
    if (error) {
      setMessages((prev) => [...prev, {
        id: `err-${Date.now()}`,
        role: 'error',
        content: error,
        timestamp: Date.now(),
      }]);
    }
  }, [error]);

  // ─── textarea 自适应 ────────────────────────────────
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(160, Math.max(56, el.scrollHeight))}px`;
  }, [input]);

  // ─── 发送 ───────────────────────────────────────────
  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || loading) return;

    // 添加用户消息
    setMessages((prev) => [...prev, {
      id: `u-${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: Date.now(),
    }]);
    setInput('');
    processedStreamIds.current.clear();

    // 启动会话
    await start(text, 'inspiration');
  }, [input, loading, start]);

  const handleSendScript = useCallback(async () => {
    const text = scriptText.trim();
    if (!text || loading) return;

    const title = text.slice(0, 60) + (text.length > 60 ? '...' : '');
    setMessages((prev) => [...prev, {
      id: `u-${Date.now()}`,
      role: 'user',
      content: `📎 上传剧本：${title}`,
      timestamp: Date.now(),
    }]);
    setScriptText('');
    processedStreamIds.current.clear();

    await start(title, 'script', text);
  }, [scriptText, loading, start]);

  const handleSendNovel = useCallback(async () => {
    const text = scriptText.trim();
    if (!text || loading) return;

    const title = text.slice(0, 60) + (text.length > 60 ? '...' : '');
    setMessages((prev) => [...prev, {
      id: `u-${Date.now()}`,
      role: 'user',
      content: `📖 上传小说：${title}`,
      timestamp: Date.now(),
    }]);
    setScriptText('');
    processedStreamIds.current.clear();

    await start(title, 'novel', text);
  }, [scriptText, loading, start]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // ─── 确认参数 ───────────────────────────────────────
  const handleConfirmParams = async () => {
    processedStreamIds.current.clear();
    await confirmParameters();
    // 移除参数卡片
    setMessages((prev) => prev.filter(m => m.cardType !== 'parameter_pending'));
  };

  // ─── 确认策划 → 进入资产 ────────────────────────────
  const handleConfirmPlanning = async () => {
    processedStreamIds.current.clear();
    await runStep('asset');
  };

  // ─── 重试策划 ───────────────────────────────────────
  const handleRetryPlanning = async () => {
    processedStreamIds.current.clear();
    renderedCardTypes.current.delete('planning_result');
    setMessages((prev) => prev.filter(m => m.cardType !== 'planning_result'));
    await runStep('planning');
  };

  // ─── 锁定资产 → 进入制作 ────────────────────────────
  const handleLockAssets = async () => {
    processedStreamIds.current.clear();
    setMessages((prev) => prev.filter(m => m.cardType !== 'asset_result'));
    await lockAssets();
  };

  // ─── 跳过资产 ───────────────────────────────────────
  const handleSkipAsset = async () => {
    processedStreamIds.current.clear();
    setMessages((prev) => prev.filter(m => m.cardType !== 'asset_result'));
    const canvasId = await skipStep();
    if (canvasId) {
      await loadCanvas(canvasId);
      closeOrNavigate();
    }
  };

  // ─── 生成并进入画布 ─────────────────────────────────
  const handleGenerateAndGo = async () => {
    const canvasId = await finalize(undefined, true);
    if (canvasId) {
      await loadCanvas(canvasId);
      closeOrNavigate();
    }
  };

  // ─── 直接进入画布 ───────────────────────────────────
  const handleEnterCanvas = async () => {
    const canvasId = await finalize(undefined, false);
    if (canvasId) {
      await loadCanvas(canvasId);
      closeOrNavigate();
    }
  };

  // ─── 重试制作 ───────────────────────────────────────
  const handleRetryProduction = async () => {
    processedStreamIds.current.clear();
    renderedCardTypes.current.delete('production_result');
    setMessages((prev) => prev.filter(m => m.cardType !== 'production_result'));
    await runStep('production');
  };

  // ─── 新对话 ─────────────────────────────────────────
  const handleNewChat = () => {
    reset();
    setMessages([]);
    setInput('');
    setScriptText('');
    processedStreamIds.current.clear();
    renderedCardTypes.current.clear();
    inputRef.current?.focus();
  };

  // ─── 恢复历史会话 ───────────────────────────────────
  const handleResumeSession = async (sid: string) => {
    processedStreamIds.current.clear();
    renderedCardTypes.current.clear();
    setMessages([]);
    await useAgentStore.getState().hydrateSession(sid);
  };

  // ─── 关闭/导航 ──────────────────────────────────────
  const closeOrNavigate = () => {
    if (page) navigate('/home');
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      setScriptText(String(ev.target?.result || ''));
    };
    reader.readAsText(file);
    e.target.value = '';
  };

  // ─── 不渲染条件 ─────────────────────────────────────
  if (!docked && !page) return null;

  // ─── 一键模式判断 ───────────────────────────────────
  const isOneClick = page && modeChosen && agentMode === 'one-click';

  const handleBackToSelector = () => {
    backToAgentSelector();
    if (page) navigate('/home');
  };

  // ════════════════════════════════════════════════════
  // Header
  // ════════════════════════════════════════════════════
  const header = (
    <div className="h-14 border-b border-panel-border flex items-center justify-between px-4 shrink-0 bg-panel-bg">
      <div className="flex items-center gap-3 min-w-0">
        {!isOneClick && !sidebarOpen && (
          <button
            onClick={() => setSidebarOpen(true)}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-theme-sub hover:text-theme-main hover:bg-panel-hover transition-colors shrink-0"
            title="展开历史"
          >
            <PanelLeftOpen size={16} />
          </button>
        )}
        <div className={`w-9 h-9 rounded-xl bg-gradient-to-br ${GRADIENT} flex items-center justify-center shadow-soft shrink-0`}>
          {isOneClick ? <Zap size={18} className="text-white" /> : <Clapperboard size={18} className="text-white" />}
        </div>
        <div className="min-w-0">
          <h2 className="text-sm font-bold text-theme-main truncate">{isOneClick ? '一键创作' : '星河 Agent'}</h2>
          <p className="text-xs text-theme-sub truncate">{isOneClick ? '全自动短剧生成' : '短剧智能创作流水线'}</p>
        </div>
      </div>
      <div className="flex items-center gap-1.5 shrink-0">
        {isOneClick ? (
          <div className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-500 text-xs font-medium">
            <Zap size={12} />
            <span>一键全自动</span>
          </div>
        ) : (
          <div className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-teal-600/10 text-teal-600 text-xs font-medium">
            <Brain size={12} className="animate-pulse" />
            <span>智能体调度</span>
          </div>
        )}
        {!isOneClick && messages.length > 0 && (
          <button
            className="w-8 h-8 rounded-lg flex items-center justify-center text-theme-sub hover:text-theme-main hover:bg-panel-hover transition-colors"
            onClick={handleNewChat}
            title="新对话"
          >
            <Plus size={16} />
          </button>
        )}
        <button
          className="w-8 h-8 rounded-lg flex items-center justify-center text-theme-sub hover:text-theme-main hover:bg-panel-hover transition-colors"
          onClick={isOneClick ? handleBackToSelector : () => {
            if (page) navigate('/home');
            else if (docked) onClose?.();
            else setSidebarOpen(false);
          }}
          title={page ? '返回首页' : docked ? '收起面板' : '收起侧栏'}
        >
          {page ? <ArrowLeft size={16} /> : <PanelLeftClose size={15} />}
        </button>
      </div>
    </div>
  );

  // ════════════════════════════════════════════════════
  // 消息区
  // ════════════════════════════════════════════════════
  const messagesArea = (
    <div ref={scrollRef} className="flex-1 overflow-y-auto">
      <div className="max-w-4xl mx-auto px-6 py-6 space-y-4">
        {messages.length === 0 && !loading && (
          /* ─── 空状态：引导卡片 ─── */
          <div className="pt-8 pb-4 text-center animate-fade-up">
            <div className={`w-16 h-16 rounded-2xl bg-gradient-to-br ${GRADIENT} flex items-center justify-center shadow-soft-lg mx-auto mb-4`}>
              <Clapperboard size={30} className="text-white" />
            </div>
            <h3 className="text-xl font-bold text-theme-main mb-1.5">星河 Agent</h3>
            <p className="text-sm text-theme-sub mb-6 max-w-md mx-auto">
              等待你的指令。输入短剧灵感或上传剧本，我会帮你完成从剧本到视频的全流程。
            </p>

            {/* 流程引导 */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 max-w-2xl mx-auto mb-6">
              {[
                { title: '前期策划', desc: '剧本架构 + 文学编剧', icon: BookOpen },
                { title: '资产设定', desc: '角色 + 场景道具', icon: User },
                { title: '拍摄制作', desc: '分镜 + 视频提示词', icon: Film },
              ].map((step, i) => (
                <div key={i} className="glass rounded-2xl border border-panel-border p-4 text-left hover:shadow-soft transition-all hover:-translate-y-0.5">
                  <div className="flex items-center gap-2 mb-2">
                    <div className={`w-6 h-6 rounded-lg bg-gradient-to-br ${GRADIENT} flex items-center justify-center text-white text-xs font-bold shrink-0`}>
                      {i + 1}
                    </div>
                    <step.icon size={14} className="text-teal-600" />
                    <span className="text-xs font-semibold text-theme-main">{step.title}</span>
                  </div>
                  <p className="text-xs text-theme-sub leading-relaxed">{step.desc}</p>
                </div>
              ))}
            </div>

            {/* 智能体调度标识 */}
            <div className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-teal-600/8 border border-teal-600/20 text-xs text-teal-600 font-medium mb-6">
              <Brain size={12} />
              总导演智能体调度 6 个子 Agent
            </div>

            {/* 示例提示词 */}
            <div className="max-w-xl mx-auto">
              <div className="text-xs text-theme-hint mb-2">试试这些爆款灵感：</div>
              <div className="flex flex-wrap gap-2 justify-center">
                {[
                  '🔥 落魄少年被豪门看不起，最后逆袭打脸',
                  '💔 女总裁隐婚三年，离婚后前夫悔不当初',
                  '⚡ 外卖小哥意外获得超能力，守护城市正义',
                  '👑 庶女入宫步步为营，在权谋斗争中逆袭',
                ].map((ex) => (
                  <button
                    key={ex}
                    onClick={() => setInput(ex.replace(/^[^\s]+\s/, ''))}
                    className="px-3 py-1.5 rounded-xl text-xs text-theme-sub border border-panel-border bg-panel-bg hover:border-teal-600/30 hover:bg-teal-600/5 hover:text-teal-600 transition-all"
                  >
                    {ex}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* 消息列表 */}
        {messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            msg={msg}
            session={session}
            selectedChars={selectedChars}
            selectedScenes={selectedScenes}
            onToggleChar={toggleChar}
            onToggleScene={toggleScene}
            onSelectAll={selectAllAssets}
            onConfirmParams={handleConfirmParams}
            onConfirmPlanning={handleConfirmPlanning}
            onRetryPlanning={handleRetryPlanning}
            onLockAssets={handleLockAssets}
            onSkipAsset={handleSkipAsset}
            onGenerateAndGo={handleGenerateAndGo}
            onEnterCanvas={handleEnterCanvas}
            onRetryProduction={handleRetryProduction}
            loading={loading}
            globalParams={globalParams}
            setGlobalParam={setGlobalParam}
          />
        ))}

        {/* 流式进度指示器 */}
        {loading && streaming && (
          <div className="flex items-start gap-2.5 animate-fade-in">
            <div className={`w-8 h-8 rounded-full shrink-0 flex items-center justify-center bg-gradient-to-br ${GRADIENT} shadow-soft`}>
              {(() => {
                const { icon: AgentIcon } = getAgentLabel(currentAgent);
                return <AgentIcon size={15} className="text-white animate-pulse" />;
              })()}
            </div>
            <div className="flex items-center gap-2.5 rounded-2xl rounded-tl-sm bg-panel-bg border border-panel-border px-4 py-3 shadow-soft">
              <TypingIndicator />
              <span className="text-sm text-theme-sub">
                {getAgentLabel(currentAgent).name} 正在工作...
              </span>
            </div>
          </div>
        )}

        {/* 非流式 loading（如启动会话） */}
        {loading && !streaming && messages.length > 0 && (
          <div className="flex items-start gap-2.5 animate-fade-in">
            <div className={`w-8 h-8 rounded-full shrink-0 flex items-center justify-center bg-gradient-to-br ${GRADIENT} shadow-soft`}>
              <Loader2 size={15} className="text-white animate-spin" />
            </div>
            <div className="flex items-center gap-2.5 rounded-2xl rounded-tl-sm bg-panel-bg border border-panel-border px-4 py-3 shadow-soft">
              <Loader2 size={14} className="text-teal-600 animate-spin" />
              <span className="text-sm text-theme-sub">正在准备...</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );

  // ════════════════════════════════════════════════════
  // 输入区
  // ════════════════════════════════════════════════════
  const inputArea = (
    <div className="border-t border-panel-border bg-panel-bg px-4 py-3 shrink-0">
      <div className="max-w-4xl mx-auto">
        {/* 模式切换 */}
        {messages.length === 0 && !session && (
          <div className="flex gap-1 p-1 rounded-xl bg-canvas-bg mb-2.5 max-w-md mx-auto">
            {([
              { key: 'inspiration', label: '灵感创作', icon: Sparkles },
              { key: 'script', label: '上传剧本', icon: BookOpen },
              { key: 'novel', label: '小说改编', icon: BookText },
            ] as const).map((tab) => (
              <button
                key={tab.key}
                className={`flex-1 py-2 rounded-lg text-xs font-medium transition-all flex items-center justify-center gap-1.5 ${
                  mode === tab.key ? `bg-gradient-to-r ${GRADIENT} text-white shadow-soft` : 'text-theme-sub hover:text-theme-main'
                }`}
                onClick={() => setMode(tab.key)}
              >
                <tab.icon size={13} /> {tab.label}
              </button>
            ))}
          </div>
        )}

        {/* 剧本/小说模式：文件上传 */}
        {(mode === 'script' || mode === 'novel') && messages.length === 0 && !session && (
          <div className="mb-2.5 max-w-4xl mx-auto">
            <input ref={fileInputRef} type="file" accept=".txt,.md,.text,.docx,.pdf" className="hidden" onChange={handleFileUpload} />
            <button
              className="w-full px-4 py-2.5 rounded-xl bg-panel-bg border border-panel-border hover:border-teal-600/30 hover:bg-teal-600/5 transition-all text-sm text-theme-main flex items-center justify-center gap-2"
              onClick={() => fileInputRef.current?.click()}
              disabled={loading}
            >
              <Upload size={16} className="text-teal-600" />
              上传{mode === 'script' ? '剧本' : '小说'}文件
            </button>
            {scriptText && (
              <div className="mt-1.5 text-xs text-theme-sub flex flex-wrap gap-2">
                <span className="px-2 py-1 rounded-lg bg-canvas-bg border border-panel-border/50">字数：{scriptText.length}</span>
                {scriptText.length > 5000 && (
                  <span className="px-2 py-1 rounded-lg bg-warning/10 text-warning border border-warning/30">文本较长，将自动分批</span>
                )}
              </div>
            )}
          </div>
        )}

        {/* 输入容器 */}
        <div className="glass rounded-2xl border border-panel-border shadow-soft overflow-hidden">
          <textarea
            ref={inputRef}
            className="w-full bg-transparent text-theme-main placeholder:text-theme-hint resize-none outline-none text-sm leading-relaxed min-h-[56px] max-h-[160px] px-4 pt-3 pb-1"
            placeholder={
              mode === 'inspiration' ? '输入短剧灵感，例如：落魄少年被豪门看不起，最后逆袭打脸...' :
              mode === 'script' ? '在此粘贴剧本文本，或点击上方按钮上传文件...' :
              '在此粘贴小说原文，或点击上方按钮上传文件...'
            }
            value={mode === 'inspiration' ? input : scriptText}
            onChange={(e) => mode === 'inspiration' ? setInput(e.target.value) : setScriptText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && mode === 'inspiration') {
                e.preventDefault();
                handleSend();
              }
            }}
            rows={2}
            disabled={loading || (!!session && mode !== 'inspiration')}
          />
          <div className="flex items-center justify-between px-3 pb-2.5 pt-1">
            <span className="text-xs text-theme-hint hidden sm:inline">
              {mode === 'inspiration' ? 'Enter 发送 · Shift+Enter 换行' : 'Ctrl+Enter 发送'}
            </span>
            <div className="flex items-center gap-2 ml-auto">
              <span className="text-xs text-theme-hint tabular-nums">
                {(mode === 'inspiration' ? input : scriptText).length}
              </span>
              <button
                onClick={() => {
                  if (mode === 'inspiration') handleSend();
                  else if (mode === 'script') handleSendScript();
                  else handleSendNovel();
                }}
                disabled={!((mode === 'inspiration' ? input : scriptText).trim()) || loading || (!!session)}
                className={`w-9 h-9 rounded-xl flex items-center justify-center text-white transition-all active:scale-95 disabled:opacity-30 disabled:cursor-not-allowed bg-gradient-to-br ${GRADIENT} shadow-soft hover:brightness-110`}
              >
                {loading ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );

  // ════════════════════════════════════════════════════
  // 历史侧栏
  // ════════════════════════════════════════════════════
  const historySidebar = (
    <div className="h-full flex flex-col bg-canvas-bg">
      <div className="p-3 border-b border-panel-border/50 flex items-center gap-2 shrink-0">
        <button
          onClick={handleNewChat}
          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl bg-gradient-to-r from-teal-600 to-emerald-500 text-white text-xs font-medium shadow-soft hover:brightness-110 transition-all"
        >
          <Plus size={14} /> 新对话
        </button>
        <button
          onClick={() => setSidebarOpen(false)}
          className="w-8 h-8 rounded-lg flex items-center justify-center text-theme-sub hover:text-theme-main hover:bg-panel-hover transition-colors lg:hidden"
          title="收起侧栏"
        >
          <PanelLeftClose size={15} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {history.length === 0 ? (
          <div className="text-center py-8 text-theme-hint text-xs leading-relaxed">
            <MessageSquare size={20} className="mx-auto mb-2 opacity-40" />
            暂无历史对话
          </div>
        ) : (
          history.map((h) => (
            <div
              key={h.id}
              onClick={() => handleResumeSession(h.id)}
              className="group flex items-start gap-2 px-3 py-2.5 rounded-xl cursor-pointer transition-all hover:bg-panel-hover border border-transparent"
            >
              <MessageSquare size={13} className="mt-0.5 shrink-0 text-theme-hint" />
              <div className="flex-1 min-w-0">
                <div className="text-xs font-medium truncate text-theme-main">{h.title}</div>
                <div className="text-[10px] text-theme-hint mt-0.5">{formatTime(h.ts)}</div>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setHistory((prev) => prev.filter((x) => x.id !== h.id));
                  localStorage.setItem('agentHistory', JSON.stringify(history.filter((x) => x.id !== h.id)));
                }}
                className="opacity-0 group-hover:opacity-100 w-6 h-6 rounded-lg flex items-center justify-center text-theme-hint hover:text-error hover:bg-error/10 transition-all shrink-0"
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );

  // ════════════════════════════════════════════════════
  // 主布局
  // ════════════════════════════════════════════════════
  const mainLayout = (
    <div className="flex-1 flex overflow-hidden">
      {sidebarOpen && (
        <>
          <div className="w-[260px] shrink-0 border-r border-panel-border hidden lg:block">
            {historySidebar}
          </div>
          <div className="lg:hidden fixed inset-0 z-[200] bg-black/30" onClick={() => setSidebarOpen(false)}>
            <div className="w-[280px] h-full bg-panel-bg" onClick={(e) => e.stopPropagation()}>
              {historySidebar}
            </div>
          </div>
        </>
      )}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* #20 主步骤进度条（始终可见） */}
        {session && !isOneClick && (
          <Stepper
            currentStep={currentStep}
            session={session}
            docked={docked}
            onGoToStep={goToStep}
          />
        )}
        {/* #15 实时步骤指示器 */}
        <StreamingStatusBar />
        {messagesArea}
        {inputArea}
      </div>
    </div>
  );

  const body = (
    <>
      {header}
      {mainLayout}
    </>
  );

  // 一键模式 body
  const oneClickBody = (
    <>
      {header}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-2xl mx-auto px-6 py-6">
          <OneClickPanel />
        </div>
      </div>
    </>
  );

  if (page) {
    return (
      <div className="h-screen w-screen bg-canvas-bg flex flex-col overflow-hidden">
        <div className="flex-1 glass rounded-none border-0 shadow-none flex flex-col overflow-hidden">
          {isOneClick ? oneClickBody : body}
        </div>
      </div>
    );
  }

  if (docked) {
    return (
      <div className="w-full h-full glass border-l border-panel-border shadow-soft-lg flex flex-col overflow-hidden">
        {body}
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-6xl h-[85vh] glass rounded-3xl border border-panel-border shadow-soft-lg flex flex-col overflow-hidden">
        {body}
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════
// 消息气泡
// ════════════════════════════════════════════════════════════════

function MessageBubble({
  msg, session, selectedChars, selectedScenes,
  onToggleChar, onToggleScene, onSelectAll,
  onConfirmParams, onConfirmPlanning, onRetryPlanning,
  onLockAssets, onSkipAsset, onGenerateAndGo, onEnterCanvas, onRetryProduction,
  loading, globalParams, setGlobalParam,
}: {
  msg: AgentChatMessage;
  session: AgentSession | null;
  selectedChars: string[];
  selectedScenes: string[];
  onToggleChar: (id: string) => void;
  onToggleScene: (id: string) => void;
  onSelectAll: () => void;
  onConfirmParams: () => void;
  onConfirmPlanning: () => void;
  onRetryPlanning: () => void;
  onLockAssets: () => void;
  onSkipAsset: () => void;
  onGenerateAndGo: () => void;
  onEnterCanvas: () => void;
  onRetryProduction: () => void;
  loading: boolean;
  globalParams: Record<string, string>;
  setGlobalParam: (key: string, value: string) => void;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard?.writeText(msg.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // ── 用户消息 ──
  if (msg.role === 'user') {
    return (
      <div className="flex justify-end items-start gap-2.5 animate-fade-up">
        <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-teal-600/8 border border-teal-600/15 px-4 py-2.5">
          <div className="text-sm text-theme-main whitespace-pre-wrap break-words leading-relaxed">{msg.content}</div>
          <div className="text-[10px] text-theme-hint mt-1 text-right">{formatTime(msg.timestamp)}</div>
        </div>
        <div className="w-8 h-8 rounded-full shrink-0 flex items-center justify-center bg-teal-600/10 border border-teal-600/20">
          <User size={15} className="text-teal-600" />
        </div>
      </div>
    );
  }

  // ── 进度消息 ──
  if (msg.role === 'progress') {
    const { name, icon: AgentIcon } = getAgentLabel(msg.agent);
    return (
      <div className="flex justify-start items-start gap-2.5 animate-fade-in">
        <div className={`w-8 h-8 rounded-full shrink-0 flex items-center justify-center bg-gradient-to-br ${GRADIENT} shadow-soft`}>
          <AgentIcon size={15} className="text-white" />
        </div>
        <div className="rounded-2xl rounded-tl-sm bg-panel-bg border border-panel-border px-4 py-2.5 shadow-soft max-w-[80%]">
          <div className="flex items-center gap-1.5 text-xs text-teal-600 mb-0.5">
            <AgentIcon size={11} />
            <span className="font-medium">{name}</span>
            <span className="text-theme-hint">· {formatTime(msg.timestamp)}</span>
          </div>
          <div className="text-sm text-theme-sub whitespace-pre-wrap break-words leading-relaxed">{msg.content}</div>
        </div>
      </div>
    );
  }

  // ── 错误消息 ──
  if (msg.role === 'error') {
    return (
      <div className="flex justify-start items-start gap-2.5 animate-fade-up">
        <div className={`w-8 h-8 rounded-full shrink-0 flex items-center justify-center bg-gradient-to-br ${GRADIENT} shadow-soft`}>
          <AlertCircle size={15} className="text-white" />
        </div>
        <div className="max-w-[75%] rounded-2xl rounded-tl-sm bg-error/8 border border-error/25 px-4 py-3">
          <div className="text-xs text-error font-semibold mb-1">执行失败</div>
          <div className="text-sm text-error/80 whitespace-pre-wrap break-words leading-relaxed">{msg.content}</div>
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

  // ── AI 回复（含结构化卡片） ──
  return (
    <div className="flex justify-start items-start gap-2.5 animate-fade-up">
      <div className={`w-8 h-8 rounded-full shrink-0 flex items-center justify-center bg-gradient-to-br ${GRADIENT} shadow-soft`}>
        <Brain size={15} className="text-white" />
      </div>
      <div className="max-w-[88%] rounded-2xl rounded-tl-sm bg-panel-bg border border-panel-border shadow-soft overflow-hidden">
        {/* 头部标识 */}
        <div className="flex items-center gap-1.5 px-4 pt-3 pb-2 text-xs text-teal-600">
          <Brain size={12} />
          <span className="font-medium">{msg.content}</span>
          <span className="text-theme-hint ml-auto">{formatTime(msg.timestamp)}</span>
        </div>

        <div className="px-4 pb-3 space-y-3">
          {/* ── 参数确认卡片 ── */}
          {msg.cardType === 'parameter_pending' && (
            <ParameterCard
              globalParams={globalParams}
              setGlobalParam={setGlobalParam}
              onConfirm={onConfirmParams}
              loading={loading}
            />
          )}

          {/* ── 策划结果卡片 ── */}
          {msg.cardType === 'planning_result' && session && (
            <PlanningResultCard
              session={session}
              onConfirm={onConfirmPlanning}
              onRetry={onRetryPlanning}
              loading={loading}
              feedback={session.feedback_message}
              retryCount={session.retry_count}
              onCopy={handleCopy}
              copied={copied}
            />
          )}

          {/* ── 资产结果卡片 ── */}
          {msg.cardType === 'asset_result' && session && (
            <AssetResultCard
              session={session}
              selectedChars={selectedChars}
              selectedScenes={selectedScenes}
              onToggleChar={onToggleChar}
              onToggleScene={onToggleScene}
              onSelectAll={onSelectAll}
              onLock={onLockAssets}
              onSkip={onSkipAsset}
              loading={loading}
              feedback={session.feedback_message}
              retryCount={session.retry_count}
            />
          )}

          {/* ── 制作结果卡片 ── */}
          {msg.cardType === 'production_result' && session && (
            <ProductionResultCard
              session={session}
              onGenerate={onGenerateAndGo}
              onEnterCanvas={onEnterCanvas}
              onRetry={onRetryProduction}
              loading={loading}
              feedback={session.feedback_message}
              retryCount={session.retry_count}
              onCopy={handleCopy}
              copied={copied}
            />
          )}

          {/* ── 完成卡片 ── */}
          {msg.cardType === 'finalized_result' && (
            <div className="text-center py-4">
              <div className="w-12 h-12 rounded-full bg-success/10 flex items-center justify-center mx-auto mb-2">
                <CheckCircle size={24} className="text-success" />
              </div>
              <div className="text-sm font-medium text-theme-main mb-1">🎉 创作完成！</div>
              <div className="text-xs text-theme-sub">画布已创建，点击下方按钮进入画布查看所有节点</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════
// 参数确认卡片
// ════════════════════════════════════════════════════════════════

function ParameterCard({
  globalParams, setGlobalParam, onConfirm, loading,
}: {
  globalParams: Record<string, string>;
  setGlobalParam: (key: string, value: string) => void;
  onConfirm: () => void;
  loading: boolean;
}) {
  return (
    <div className="space-y-3">
      <div className="text-xs text-theme-sub leading-relaxed">
        AI 已根据你的输入推荐以下全局参数，确认后将开始创作。
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {GLOBAL_PARAM_DEFINITIONS.map((def) => (
          <div key={def.key} className="space-y-1">
            <label className="text-xs text-theme-sub flex items-center gap-1">
              {def.label}
              {def.editable === false && (
                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-teal-600/10 text-teal-600">自动</span>
              )}
            </label>
            {def.type === 'select' ? (
              <select
                className="w-full text-sm bg-canvas-bg border border-panel-border/60 rounded-xl px-3 py-2 text-theme-main outline-none focus:border-teal-600/50 transition-all disabled:opacity-50"
                value={globalParams[def.key] ?? ''}
                onChange={(e) => setGlobalParam(def.key, e.target.value)}
                disabled={loading}
              >
                {def.options?.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            ) : (
              <input
                type="text"
                className="w-full text-sm bg-canvas-bg border border-panel-border/60 rounded-xl px-3 py-2 text-theme-main outline-none focus:border-teal-600/50 transition-all disabled:opacity-50"
                value={globalParams[def.key] ?? ''}
                onChange={(e) => setGlobalParam(def.key, e.target.value)}
                disabled={def.editable === false || loading}
              />
            )}
          </div>
        ))}
      </div>
      <button
        className="w-full btn-primary text-sm py-2.5"
        onClick={onConfirm}
        disabled={loading}
      >
        {loading ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle size={14} />}
        <span>确认参数，开始创作</span>
      </button>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════
// 策划结果卡片
// ════════════════════════════════════════════════════════════════

function PlanningResultCard({
  session, onConfirm, onRetry, loading, feedback, retryCount, onCopy, copied,
}: {
  session: AgentSession;
  onConfirm: () => void;
  onRetry: () => void;
  loading: boolean;
  feedback?: string;
  retryCount?: number;
  onCopy: () => void;
  copied: boolean;
}) {
  const [expanded, setExpanded] = useState(true);
  const script = session.script_outline || session.script;
  const screenwriter = session.full_script || session.screenwriter;
  const sp = screenwriter?.screenplay;

  const episodes = sp?.episodes || script?.episodes || [];
  const totalDuration = (sp as any)?.total_duration || 0;
  const totalScenes = episodes.reduce((sum, ep) => sum + (ep.scenes?.length || 0), 0);

  return (
    <div className="space-y-3">
      {/* 质检反馈 */}
      {feedback && (
        <div className="rounded-xl border-l-4 border-warning bg-warning/5 p-3">
          <div className="flex items-center gap-2 text-warning text-xs font-bold mb-1">
            <AlertCircle size={14} />
            <span>导演质检反馈{retryCount ? `（第 ${retryCount} 次重试）` : ''}</span>
          </div>
          <div className="text-xs text-theme-sub leading-relaxed">{feedback}</div>
        </div>
      )}

      {/* 项目概要 */}
      {script && (
        <div className="rounded-xl bg-canvas-bg/50 border border-panel-border/40 p-3">
          <div className="flex items-center gap-2 mb-2">
            <BookOpen size={14} className="text-teal-600" />
            <span className="text-sm font-bold text-theme-main">{script.project_title || '未命名'}</span>
            <span className="text-xs text-theme-sub">{script.genre}</span>
          </div>
          <div className="flex flex-wrap gap-1.5 mb-2">
            <span className="text-xs px-2 py-0.5 rounded-full bg-canvas-bg border border-panel-border text-theme-sub">{episodes.length} 集</span>
            <span className="text-xs px-2 py-0.5 rounded-full bg-canvas-bg border border-panel-border text-theme-sub">{totalScenes} 场</span>
            {totalDuration > 0 && <span className="text-xs px-2 py-0.5 rounded-full bg-canvas-bg border border-panel-border text-theme-sub">约 {totalDuration}s</span>}
          </div>
          {script.style_bible && (
            <div className="text-xs text-theme-sub leading-relaxed">🎨 {script.style_bible}</div>
          )}
        </div>
      )}

      {/* 分集大纲 */}
      {episodes.length > 0 && (
        <div className="rounded-xl bg-canvas-bg/50 border border-panel-border/40 overflow-hidden">
          <button
            className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold text-theme-main hover:bg-panel-hover transition-colors"
            onClick={() => setExpanded((v) => !v)}
          >
            <span className="flex items-center gap-1.5">
              <BookText size={13} className="text-teal-600" />
              分集剧本详情
            </span>
            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
          {expanded && (
            <div className="px-3 pb-3 space-y-2 max-h-[400px] overflow-y-auto">
              {episodes.map((ep: any) => (
                <div key={ep.episode_num} className="border border-panel-border/30 rounded-lg p-2.5 bg-panel-bg/50">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-bold text-teal-600">第{ep.episode_num}集</span>
                    <span className="text-xs text-theme-sub flex-1 truncate">{ep.logline}</span>
                    {ep.total_duration && <span className="text-[10px] text-theme-hint">{ep.total_duration}s</span>}
                  </div>
                  {ep.scenes?.map((scene: any) => (
                    <div key={scene.scene_id} className="text-xs text-theme-sub leading-relaxed pl-2 border-l-2 border-panel-border/30 mt-1">
                      <span className="font-medium text-theme-main">{scene.scene_id}</span>
                      {' '}{scene.location} · {scene.time}
                      {scene.action_description && <div className="text-theme-sub mt-0.5">{scene.action_description.slice(0, 100)}{scene.action_description.length > 100 ? '...' : ''}</div>}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 操作栏 */}
      <div className="flex items-center gap-2">
        <button onClick={onCopy} className="text-xs text-theme-sub hover:text-teal-600 flex items-center gap-1 transition-colors">
          {copied ? <Check size={12} className="text-success" /> : <Copy size={12} />}
          {copied ? '已复制' : '复制'}
        </button>
        <div className="flex-1" />
        {feedback && retryCount && retryCount < DRAMA_MAX_RETRIES && (
          <button
            onClick={onRetry}
            disabled={loading}
            className="text-xs px-3 py-1.5 rounded-xl border border-warning/30 text-warning hover:bg-warning/10 transition-all flex items-center gap-1"
          >
            <RotateCcw size={12} /> 修改重试
          </button>
        )}
        <button
          onClick={onConfirm}
          disabled={loading}
          className="text-xs px-4 py-1.5 rounded-xl bg-gradient-to-r from-teal-600 to-emerald-500 text-white font-medium shadow-soft hover:brightness-110 transition-all flex items-center gap-1 disabled:opacity-50"
        >
          {loading ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle size={12} />}
          确认进入资产设定
        </button>
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════
// 资产结果卡片
// ════════════════════════════════════════════════════════════════

function AssetResultCard({
  session, selectedChars, selectedScenes,
  onToggleChar, onToggleScene, onSelectAll,
  onLock, onSkip, loading, feedback, retryCount,
}: {
  session: AgentSession;
  selectedChars: string[];
  selectedScenes: string[];
  onToggleChar: (id: string) => void;
  onToggleScene: (id: string) => void;
  onSelectAll: () => void;
  onLock: () => void;
  onSkip: () => void;
  loading: boolean;
  feedback?: string;
  retryCount?: number;
}) {
  const characters = session.character_assets?.characters || session.character?.characters || session.assets?.characters || [];
  const scenes = session.scene_assets?.scenes || session.scene?.scenes || session.assets?.scenes || [];

  return (
    <div className="space-y-3">
      {/* 质检反馈 */}
      {feedback && (
        <div className="rounded-xl border-l-4 border-warning bg-warning/5 p-3">
          <div className="flex items-center gap-2 text-warning text-xs font-bold mb-1">
            <AlertCircle size={14} />
            <span>导演质检反馈{retryCount ? `（第 ${retryCount} 次重试）` : ''}</span>
          </div>
          <div className="text-xs text-theme-sub leading-relaxed">{feedback}</div>
        </div>
      )}

      {/* 角色列表 */}
      {characters.length > 0 && (
        <div className="rounded-xl bg-canvas-bg/50 border border-panel-border/40 p-3">
          <div className="flex items-center gap-2 mb-2">
            <User size={14} className="text-teal-600" />
            <span className="text-sm font-bold text-theme-main">角色设定（{characters.length}）</span>
          </div>
          <div className="space-y-1.5 max-h-[250px] overflow-y-auto">
            {characters.map((c: any) => (
              <label
                key={c.char_id}
                className={`flex items-start gap-2 p-2 rounded-lg cursor-pointer transition-all border ${
                  selectedChars.includes(c.char_id)
                    ? 'bg-teal-600/8 border-teal-600/30'
                    : 'border-transparent hover:bg-panel-hover'
                }`}
              >
                <input
                  type="checkbox"
                  className="mt-0.5 accent-teal-600"
                  checked={selectedChars.includes(c.char_id)}
                  onChange={() => onToggleChar(c.char_id)}
                  disabled={loading}
                />
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-medium text-theme-main">
                    {c.name} <span className="text-theme-hint font-normal">· {c.role}</span>
                  </div>
                  <div className="text-[11px] text-theme-sub truncate">{c.visual_anchor}</div>
                </div>
              </label>
            ))}
          </div>
        </div>
      )}

      {/* 场景列表 */}
      {scenes.length > 0 && (
        <div className="rounded-xl bg-canvas-bg/50 border border-panel-border/40 p-3">
          <div className="flex items-center gap-2 mb-2">
            <LayoutGrid size={14} className="text-teal-600" />
            <span className="text-sm font-bold text-theme-main">场景设定（{scenes.length}）</span>
          </div>
          <div className="space-y-1.5 max-h-[200px] overflow-y-auto">
            {scenes.map((s: any) => (
              <label
                key={s.scene_id}
                className={`flex items-start gap-2 p-2 rounded-lg cursor-pointer transition-all border ${
                  selectedScenes.includes(s.scene_id)
                    ? 'bg-teal-600/8 border-teal-600/30'
                    : 'border-transparent hover:bg-panel-hover'
                }`}
              >
                <input
                  type="checkbox"
                  className="mt-0.5 accent-teal-600"
                  checked={selectedScenes.includes(s.scene_id)}
                  onChange={() => onToggleScene(s.scene_id)}
                  disabled={loading}
                />
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-medium text-theme-main">
                    {s.name} <span className="text-theme-hint font-normal">· {s.scene_id}</span>
                  </div>
                  <div className="text-[11px] text-theme-sub truncate">{s.base_prompt?.slice(0, 80)}</div>
                </div>
              </label>
            ))}
          </div>
        </div>
      )}

      {/* 操作栏 */}
      <div className="flex items-center gap-2">
        <button
          onClick={onSelectAll}
          disabled={loading}
          className="text-xs px-3 py-1.5 rounded-xl border border-panel-border text-theme-sub hover:text-theme-main hover:bg-panel-hover transition-all"
        >
          全选
        </button>
        <div className="flex-1" />
        <button
          onClick={onSkip}
          disabled={loading}
          className="text-xs px-3 py-1.5 rounded-xl border border-panel-border text-theme-sub hover:text-theme-main hover:bg-panel-hover transition-all"
        >
          跳过进入画布
        </button>
        <button
          onClick={onLock}
          disabled={loading || (selectedChars.length === 0 && selectedScenes.length === 0)}
          className="text-xs px-4 py-1.5 rounded-xl bg-gradient-to-r from-teal-600 to-emerald-500 text-white font-medium shadow-soft hover:brightness-110 transition-all flex items-center gap-1 disabled:opacity-50"
        >
          {loading ? <Loader2 size={12} className="animate-spin" /> : <Lock size={12} />}
          锁定资产（{selectedChars.length + selectedScenes.length}）
        </button>
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════
// 制作结果卡片
// ════════════════════════════════════════════════════════════════

function ProductionResultCard({
  session, onGenerate, onEnterCanvas, onRetry, loading, feedback, retryCount, onCopy, copied,
}: {
  session: AgentSession;
  onGenerate: () => void;
  onEnterCanvas: () => void;
  onRetry: () => void;
  loading: boolean;
  feedback?: string;
  retryCount?: number;
  onCopy: () => void;
  copied: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const storyboard = session.storyboard_data || session.storyboard;
  const videoPlan = session.video_plan || session.videos;
  const storyboards = storyboard?.storyboards || [];
  const videos = videoPlan?.videos || [];

  return (
    <div className="space-y-3">
      {/* 质检反馈 */}
      {feedback && (
        <div className="rounded-xl border-l-4 border-warning bg-warning/5 p-3">
          <div className="flex items-center gap-2 text-warning text-xs font-bold mb-1">
            <AlertCircle size={14} />
            <span>导演质检反馈{retryCount ? `（第 ${retryCount} 次重试）` : ''}</span>
          </div>
          <div className="text-xs text-theme-sub leading-relaxed">{feedback}</div>
        </div>
      )}

      {/* 分镜概要 */}
      {storyboards.length > 0 && (
        <div className="rounded-xl bg-canvas-bg/50 border border-panel-border/40 p-3">
          <div className="flex items-center gap-2 mb-2">
            <Clapperboard size={14} className="text-teal-600" />
            <span className="text-sm font-bold text-theme-main">分镜表（{storyboards.length} 镜）</span>
          </div>
          <div className="space-y-1 max-h-[200px] overflow-y-auto">
            {storyboards.slice(0, expanded ? undefined : 5).map((sb: any, i: number) => (
              <div key={i} className="text-xs text-theme-sub border-l-2 border-panel-border/30 pl-2 py-0.5">
                <span className="font-medium text-theme-main">{sb.shot_id || `镜${i + 1}`}</span>
                {' '}{sb.shot_type} · {sb.duration}s
                {sb.action_description && <div className="text-theme-sub truncate">{sb.action_description?.slice(0, 80)}</div>}
              </div>
            ))}
          </div>
          {storyboards.length > 5 && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="text-xs text-teal-600 hover:underline mt-1.5 flex items-center gap-1"
            >
              {expanded ? <><ChevronUp size={12} />收起</> : <><ChevronDown size={12} />查看全部 {storyboards.length} 镜</>}
            </button>
          )}
        </div>
      )}

      {/* 视频提示词概要 */}
      {videos.length > 0 && (
        <div className="rounded-xl bg-canvas-bg/50 border border-panel-border/40 p-3">
          <div className="flex items-center gap-2 mb-2">
            <Film size={14} className="text-teal-600" />
            <span className="text-sm font-bold text-theme-main">视频提示词（{videos.length} 个）</span>
          </div>
          <div className="text-xs text-theme-sub leading-relaxed">
            已为 {videos.length} 个分镜生成 Seedance 2.0 标准视频提示词，可在画布中查看详情并生成视频。
          </div>
        </div>
      )}

      {/* 操作栏 */}
      <div className="flex items-center gap-2">
        <button onClick={onCopy} className="text-xs text-theme-sub hover:text-teal-600 flex items-center gap-1 transition-colors">
          {copied ? <Check size={12} className="text-success" /> : <Copy size={12} />}
          {copied ? '已复制' : '复制'}
        </button>
        <div className="flex-1" />
        {feedback && retryCount && retryCount < DRAMA_MAX_RETRIES && (
          <button
            onClick={onRetry}
            disabled={loading}
            className="text-xs px-3 py-1.5 rounded-xl border border-warning/30 text-warning hover:bg-warning/10 transition-all flex items-center gap-1"
          >
            <RotateCcw size={12} /> 修改重试
          </button>
        )}
        <button
          onClick={onEnterCanvas}
          disabled={loading}
          className="text-xs px-3 py-1.5 rounded-xl border border-panel-border text-theme-sub hover:text-theme-main hover:bg-panel-hover transition-all flex items-center gap-1"
        >
          <LayoutGrid size={12} /> 进入画布
        </button>
        <button
          onClick={onGenerate}
          disabled={loading}
          className="text-xs px-4 py-1.5 rounded-xl bg-gradient-to-r from-teal-600 to-emerald-500 text-white font-medium shadow-soft hover:brightness-110 transition-all flex items-center gap-1 disabled:opacity-50"
        >
          {loading ? <Loader2 size={12} className="animate-spin" /> : <ImageIcon size={12} />}
          生成图片进入画布
        </button>
      </div>
    </div>
  );
}
