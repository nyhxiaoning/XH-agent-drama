/**
 * OneClickPanel + OneClickProgress
 * 一键全自动短剧创作：从灵感到画布全节点，生图/生视频需用户手动确认。
 */
import { useState } from 'react';
import {
  Zap, Send, Loader2, Sparkles, CheckCircle, Film,
  ImageIcon, AlertCircle, ArrowRight, RotateCcw, BookText, Upload,
} from 'lucide-react';
import { useAgentStore } from '@/store/agent';
import { useNavigate } from 'react-router-dom';
import { useEditorStore } from '@/store/editor';

const STAGE_INFO: Record<string, { label: string; icon: typeof Zap }> = {
  auto_params: { label: '参数推断', icon: Sparkles },
  planning: { label: '剧本创作', icon: Zap },
  asset: { label: '资产提取', icon: ImageIcon },
  auto_lock: { label: '资产锁定', icon: CheckCircle },
  production: { label: '分镜制作', icon: Film },
  finalize: { label: '画布创建', icon: CheckCircle },
};

export function OneClickPanel() {
  const { oneClickStart, oneClickRunning, oneClickMessages } = useAgentStore();
  const [input, setInput] = useState('');
  const [oneClickMode, setOneClickMode] = useState<'inspiration' | 'novel'>('inspiration');
  const [novelText, setNovelText] = useState('');

  const examples = [
    '穿越古代男频醉卧美人膝的爽剧',
    '女总裁隐婚三年，离婚后前夫悔不当初',
    '外卖小哥意外获得超能力，守护城市正义',
    '庶女入宫步步为营，在权谋斗争中逆袭',
  ];

  const handleStart = () => {
    const text = input.trim();
    if (!text) return;
    oneClickStart(text);
  };

  const handleStartNovel = () => {
    const text = novelText.trim();
    if (!text) return;
    oneClickStart(text.slice(0, 80) + (text.length > 80 ? '...' : text), 'novel', text);
  };

  // 如果正在运行或已有进度消息，显示进度面板
  if (oneClickRunning || oneClickMessages.length > 0) {
    return <OneClickProgress />;
  }

  return (
    <div className="max-w-2xl mx-auto space-y-4">
      {/* 标题区 */}
      <div className="text-center">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-gradient-to-r from-emerald-500/20 to-teal-600/20 border border-teal-600/30 mb-3">
          <Zap size={12} className="text-emerald-500" />
          <span className="text-xs font-medium text-emerald-500">一键模式 · 全自动</span>
        </div>
        <h3 className="text-xl sm:text-2xl font-bold text-theme-main mb-1">一键生成短剧</h3>
        <p className="text-xs text-theme-sub leading-relaxed">
          输入一句话灵感，AI 自动完成参数推断 → 剧本创作 → 资产锁定 → 分镜制作 → 画布创建。
          <br />
          <span className="text-warning/80">生图和生视频需在画布中手动确认触发（涉及费用）。</span>
        </p>
      </div>

      {/* 输入区 */}
      <div className="glass rounded-2xl border border-panel-border/60 shadow-soft-lg p-5">
        {/* 模式切换 */}
        <div className="flex gap-1 p-1 rounded-xl bg-canvas-bg mb-4">
          <button
            className={`flex-1 py-2.5 rounded-lg text-sm font-medium transition-all flex items-center justify-center gap-1.5 ${
              oneClickMode === 'inspiration' ? 'bg-gradient-to-r from-emerald-500 to-teal-600 text-white shadow-soft' : 'text-theme-sub hover:text-theme-main'
            }`}
            onClick={() => setOneClickMode('inspiration')}
          >
            <Sparkles size={14} /> 灵感模式
          </button>
          <button
            className={`flex-1 py-2.5 rounded-lg text-sm font-medium transition-all flex items-center justify-center gap-1.5 ${
              oneClickMode === 'novel' ? 'bg-gradient-to-r from-emerald-500 to-teal-600 text-white shadow-soft' : 'text-theme-sub hover:text-theme-main'
            }`}
            onClick={() => setOneClickMode('novel')}
          >
            <BookText size={14} /> 小说改编
          </button>
        </div>

        {oneClickMode === 'inspiration' ? (
          <>
            <div className="relative">
              <textarea
                className="w-full min-h-[100px] rounded-xl bg-canvas-bg border border-panel-border/60 px-4 py-3 text-sm text-theme-main placeholder:text-theme-hint resize-none outline-none focus:border-teal-600/50 transition-all"
                placeholder="输入你的短剧灵感，例如：穿越古代男频醉卧美人膝的爽剧..."
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault();
                    handleStart();
                  }
                }}
              />
              <div className="absolute bottom-2 right-2">
                <button
                  className="w-9 h-9 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 hover:brightness-110 disabled:opacity-40 flex items-center justify-center text-white transition-all shadow-soft active:scale-95"
                  onClick={handleStart}
                  disabled={!input.trim()}
                  title="一键启动"
                >
                  <Send size={14} />
                </button>
              </div>
            </div>

            {/* 爆款灵感 */}
            <div className="mt-4">
              <div className="text-xs text-theme-sub mb-2 flex items-center gap-1.5">
                <Sparkles size={12} className="text-emerald-500" /> 试试这些爆款灵感
              </div>
              <div className="flex flex-wrap gap-2">
                {examples.map((ex) => (
                  <button
                    key={ex}
                    className="px-3 py-1.5 rounded-xl text-xs border border-panel-border bg-panel-bg text-theme-main hover:border-teal-600/30 hover:bg-emerald-500/5 hover:text-emerald-500 transition-all"
                    onClick={() => setInput(ex)}
                  >
                    {ex}
                  </button>
                ))}
              </div>
            </div>
          </>
        ) : (
          <div className="space-y-3">
            <div className="flex items-start gap-2 p-3 rounded-xl bg-emerald-500/5 border border-emerald-500/20">
              <BookText size={14} className="text-emerald-500 shrink-0 mt-0.5" />
              <p className="text-xs text-theme-sub leading-relaxed">
                粘贴小说原文，AI 将自动改编为短剧大纲并完成全自动流水线。
              </p>
            </div>
            <textarea
              className="w-full h-40 px-4 py-3 rounded-xl bg-canvas-bg border border-panel-border/60 text-sm text-theme-main resize-none outline-none focus:border-teal-600/50 transition-all placeholder:text-theme-hint"
              placeholder="在此粘贴小说原文...&#10;&#10;支持任意题材，建议 2000 字以上片段。"
              value={novelText}
              onChange={(e) => setNovelText(e.target.value)}
            />
            <button
              className="w-full btn-primary text-sm py-2.5"
              onClick={handleStartNovel}
              disabled={!novelText.trim()}
            >
              {<BookText size={14} />}
              <span>一键改编小说</span>
            </button>
          </div>
        )}
      </div>

      {/* 流程说明 */}
      <div className="glass rounded-2xl border border-panel-border/40 p-4">
        <div className="text-xs font-medium text-theme-sub mb-3 flex items-center gap-1.5">
          <Zap size={12} className="text-emerald-500" /> 自动流程
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {[
            { label: '参数推断', icon: Sparkles },
            { label: '剧本创作', icon: Zap },
            { label: '资产提取', icon: ImageIcon },
            { label: '资产锁定', icon: CheckCircle },
            { label: '分镜制作', icon: Film },
            { label: '画布创建', icon: CheckCircle },
          ].map((s, i) => (
            <div key={s.label} className="flex items-center gap-2">
              <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-teal-600/10 border border-emerald-500/20">
                <s.icon size={12} className="text-emerald-500" />
                <span className="text-[11px] text-theme-main">{s.label}</span>
              </div>
              {i < 5 && <ArrowRight size={10} className="text-theme-hint" />}
            </div>
          ))}
        </div>
        <div className="mt-3 pt-3 border-t border-panel-border/40">
          <div className="text-[11px] text-warning/80 flex items-center gap-1.5">
            <AlertCircle size={11} />
            生图/生视频不自动触发，需在画布中手动确认（涉及费用）
          </div>
        </div>
      </div>
    </div>
  );
}

export function OneClickProgress() {
  const navigate = useNavigate();
  const {
    oneClickRunning, oneClickProgress, oneClickStage,
    oneClickMessages, oneClickCanvasId, oneClickReset, error,
  } = useAgentStore();
  const loadCanvas = useEditorStore((s) => s.loadCanvas);

  const stageInfo = oneClickStage ? STAGE_INFO[oneClickStage] : null;
  const StageIcon = stageInfo?.icon || Loader2;

  const handleGoToCanvas = async () => {
    if (oneClickCanvasId) {
      await loadCanvas(oneClickCanvasId);
      navigate('/home');
    }
  };

  const handleRestart = () => {
    oneClickReset();
    useAgentStore.getState().reset();
    // 重新创作后保持一键模式
    useAgentStore.getState().chooseAgentMode('one-click');
  };

  return (
    <div className="max-w-2xl mx-auto space-y-4">
      {/* 进度头部 */}
      <div className="glass rounded-2xl border border-panel-border/60 shadow-soft-lg p-5">
        <div className="flex items-center gap-3 mb-4">
          <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${
            oneClickRunning ? 'bg-emerald-500/15 text-emerald-500' : oneClickCanvasId ? 'bg-success/15 text-success' : 'bg-warning/15 text-warning'
          }`}>
            <StageIcon size={18} className={oneClickRunning ? 'animate-spin' : ''} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-bold text-theme-main">
              {oneClickRunning ? (stageInfo?.label || 'AI 正在创作') : oneClickCanvasId ? '创作完成！' : '创作中断'}
            </div>
            <div className="text-[11px] text-theme-sub">
              {oneClickRunning ? `当前阶段：${oneClickStage || '初始化'} · 进度 ${oneClickProgress}%` : '可在画布中查看并手动生成图片/视频'}
            </div>
          </div>
          {oneClickRunning && (
            <div className="text-2xl font-bold tabular-nums text-emerald-500">
              {oneClickProgress}%
            </div>
          )}
        </div>

        {/* 总进度条 */}
        <div className="h-2.5 bg-panel-border/30 rounded-full overflow-hidden mb-2">
          <div
            className="h-full bg-gradient-to-r from-emerald-500 to-teal-600 rounded-full transition-all duration-700"
            style={{
              width: `${oneClickProgress}%`,
              animation: oneClickRunning ? 'pulse 2s ease-in-out infinite' : undefined,
            }}
          />
        </div>

        {/* 阶段列表 */}
        <div className="grid grid-cols-6 gap-1.5 mt-3">
          {Object.entries(STAGE_INFO).map(([key, info]) => {
            const isDone = oneClickMessages.some(m => m.step === `${key}_progress` || m.step === 'stage_done' && m.content?.includes(info.label));
            const stageDone = oneClickMessages.some(m => m.step === 'stage_done' && m.content?.includes(info.label));
            const isCurrent = oneClickStage === key;
            return (
              <div
                key={key}
                className={`flex flex-col items-center gap-1 p-2 rounded-lg transition-all ${
                  stageDone ? 'bg-success/10' : isCurrent ? 'bg-teal-600/10' : 'bg-canvas-bg/50'
                }`}
              >
                <info.icon
                  size={14}
                  className={
                    stageDone ? 'text-success' : isCurrent ? 'text-emerald-500 animate-pulse' : 'text-theme-hint'
                  }
                />
                <span className={`text-[10px] text-center ${
                  stageDone ? 'text-success' : isCurrent ? 'text-emerald-500 font-medium' : 'text-theme-hint'
                }`}>
                  {info.label}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* 消息流 */}
      {oneClickMessages.length > 0 && (
        <div className="glass rounded-2xl border border-panel-border/40 p-4 max-h-[300px] overflow-y-auto">
          <div className="text-xs font-medium text-theme-sub mb-3 flex items-center gap-1.5">
            <Sparkles size={12} className="text-emerald-500" /> 创作日志
          </div>
          <div className="space-y-2">
            {oneClickMessages.map((msg, i) => (
              <div key={i} className="flex items-start gap-2 text-xs animate-fade-up">
                <div className={`w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 ${
                  msg.step === 'error' ? 'bg-error' : msg.step === 'stage_done' ? 'bg-success' : 'bg-teal-500'
                }`} />
                <div className="flex-1 min-w-0">
                  <span className={msg.step === 'error' ? 'text-error' : msg.step === 'stage_done' ? 'text-success' : 'text-theme-sub'}>
                    {msg.content}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 错误提示 */}
      {error && (
        <div className="glass rounded-2xl border border-error/30 p-4">
          <div className="flex items-start gap-2">
            <AlertCircle size={16} className="text-error shrink-0 mt-0.5" />
            <div>
              <div className="text-sm font-medium text-error mb-1">创作出错</div>
              <div className="text-xs text-theme-sub">{error}</div>
            </div>
          </div>
        </div>
      )}

      {/* 操作按钮 */}
      {!oneClickRunning && (
        <div className="flex gap-3">
          {oneClickCanvasId && (
            <button
              className="flex-1 btn-primary text-sm py-2.5 flex items-center justify-center gap-2"
              onClick={handleGoToCanvas}
            >
              <Film size={14} />
              <span>进入画布手动生图/生视频</span>
            </button>
          )}
          <button
            className="px-4 py-2.5 rounded-xl bg-panel-bg border border-panel-border hover:border-teal-600/30 text-sm text-theme-main flex items-center gap-2"
            onClick={handleRestart}
          >
            <RotateCcw size={14} />
            重新创作
          </button>
        </div>
      )}
    </div>
  );
}
