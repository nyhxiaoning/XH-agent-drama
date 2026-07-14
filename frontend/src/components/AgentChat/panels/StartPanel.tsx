/**
 * P4: StartPanel + ScriptUploadStats + ParameterPendingPanel（重构版）
 * - tab按钮增大 + 图标
 * - 模型选择器改为横向chips
 * - 示例灵感改为卡片式
 * - 整体视觉层次增强
 */
import { useState, useRef, useEffect } from 'react';
import {
  Sparkles, BookOpen, Send, Loader2, Upload, PenLine,
  CheckCircle, Zap, Image as ImageIcon, Film, History, X, BookText,
} from 'lucide-react';
import { useAgentStore } from '@/store/agent';
import { StepOptionsPanel, LlmModelSelector, CostEstimateBadge } from '../Controls';
import { GLOBAL_PARAM_DEFINITIONS } from '../constants';

export function StartPanel() {
  const examples = [
    { text: '落魄少年被豪门看不起，最后逆袭打脸', icon: '🔥' },
    { text: '女总裁隐婚三年，离婚后前夫悔不当初', icon: '💔' },
    { text: '外卖小哥意外获得超能力，守护城市正义', icon: '⚡' },
    { text: '庶女入宫步步为营，在权谋斗争中逆袭，最终登上后位', icon: '👑' },
  ];
  const { start, loading, selectedLlmModel, setSelectedLlmModel, hydrateSession, loadSavedSessionId } = useAgentStore();
  const [tab, setTab] = useState<'inspiration' | 'script' | 'novel'>('inspiration');
  const [customInput, setCustomInput] = useState('');
  const [scriptText, setScriptText] = useState('');
  const [novelText, setNovelText] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const novelFileInputRef = useRef<HTMLInputElement>(null);
  const [savedSessionId, setSavedSessionId] = useState<string | null>(null);
  const [resuming, setResuming] = useState(false);

  useEffect(() => {
    const sid = loadSavedSessionId();
    if (sid) setSavedSessionId(sid);
  }, [loadSavedSessionId]);

  const handleResume = async () => {
    if (!savedSessionId) return;
    setResuming(true);
    try {
      await hydrateSession(savedSessionId);
    } catch {
      setSavedSessionId(null);
    } finally {
      setResuming(false);
    }
  };

  const handleDismissResume = () => {
    setSavedSessionId(null);
  };

  const handleFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = String(e.target?.result || '');
      setScriptText(text);
    };
    reader.readAsText(file);
  };

  const handleNovelFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = String(e.target?.result || '');
      setNovelText(text);
    };
    reader.readAsText(file);
  };

  const handleStartScript = () => {
    const text = scriptText.trim();
    if (!text) return;
    start(text.slice(0, 80) + (text.length > 80 ? '...' : text), 'script', text);
  };

  const handleStartNovel = () => {
    const text = novelText.trim();
    if (!text) return;
    start(text.slice(0, 80) + (text.length > 80 ? '...' : text), 'novel', text);
  };

  const handleStartInspiration = () => {
    const text = customInput.trim();
    if (!text) return;
    start(text);
  };

  return (
    <div className="max-w-2xl mx-auto space-y-4">
      {/* 恢复未完成会话 */}
      {savedSessionId && (
        <div className="glass rounded-2xl border border-indigo-500/25 shadow-soft p-3 flex items-center gap-3 animate-fade-up">
          <div className="w-9 h-9 rounded-xl bg-indigo-500/12 text-indigo-500 flex items-center justify-center shrink-0">
            <History size={16} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-theme-main">发现未完成的创作会话</div>
            <div className="text-xs text-theme-sub">点击继续上次的创作进度</div>
          </div>
          <button
            className="btn-primary text-xs px-3 py-1.5"
            onClick={handleResume}
            disabled={resuming}
          >
            {resuming ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
            <span>继续创作</span>
          </button>
          <button className="text-theme-hint hover:text-theme-main transition-colors" onClick={handleDismissResume}>
            <X size={14} />
          </button>
        </div>
      )}

      {/* 标题 */}
      <div className="text-center">
        <h3 className="text-xl sm:text-2xl font-bold text-theme-main mb-1">开始你的短剧创作</h3>
        <p className="text-xs text-theme-sub">
          灵感模式从零开始策划；剧本模式直接拆解完整剧本；小说模式将小说原文改编为短剧大纲。
        </p>
      </div>

      <div className="glass rounded-2xl border border-panel-border/60 shadow-soft p-5">
        {/* Tab 切换 */}
        <div className="flex gap-1 p-1 rounded-xl bg-canvas-bg mb-5">
          <button
            className={`flex-1 py-2.5 rounded-lg text-sm font-medium transition-all flex items-center justify-center gap-1.5 ${
              tab === 'inspiration' ? 'bg-gradient-to-r from-indigo-500 to-violet-500 text-white shadow-soft' : 'text-theme-sub hover:text-theme-main'
            }`}
            onClick={() => setTab('inspiration')}
          >
            <Sparkles size={15} /> 灵感创作
          </button>
          <button
            className={`flex-1 py-2.5 rounded-lg text-sm font-medium transition-all flex items-center justify-center gap-1.5 ${
              tab === 'script' ? 'bg-gradient-to-r from-indigo-500 to-violet-500 text-white shadow-soft' : 'text-theme-sub hover:text-theme-main'
            }`}
            onClick={() => setTab('script')}
          >
            <BookOpen size={15} /> 上传剧本
          </button>
          <button
            className={`flex-1 py-2.5 rounded-lg text-sm font-medium transition-all flex items-center justify-center gap-1.5 ${
              tab === 'novel' ? 'bg-gradient-to-r from-indigo-500 to-violet-500 text-white shadow-soft' : 'text-theme-sub hover:text-theme-main'
            }`}
            onClick={() => setTab('novel')}
          >
            <BookText size={15} /> 小说改编
          </button>
        </div>

        {/* 模型选择 */}
        <div className="mb-5">
          <LlmModelSelector
            selected={selectedLlmModel}
            onSelect={setSelectedLlmModel}
            disabled={loading}
          />
        </div>

        {tab === 'inspiration' ? (
          <div className="space-y-5 animate-fade-up">
            <div className="relative">
              <textarea
                className="w-full min-h-[100px] rounded-xl bg-canvas-bg border border-panel-border/60 px-4 py-3 text-sm text-theme-main placeholder:text-theme-hint resize-none outline-none focus:border-indigo-500/50 transition-all"
                placeholder="输入你的短剧灵感，例如：落魄少年被豪门看不起，最后逆袭打脸..."
                value={customInput}
                onChange={(e) => setCustomInput(e.target.value)}
                disabled={loading}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault();
                    handleStartInspiration();
                  } else if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleStartInspiration();
                  }
                }}
              />
              <div className="absolute bottom-2 right-2">
                <button
                  className="w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-500 to-violet-500 hover:brightness-110 disabled:opacity-40 flex items-center justify-center text-white transition-all shadow-soft active:scale-95"
                  onClick={handleStartInspiration}
                  disabled={loading || !customInput.trim()}
                  title="开始创作"
                >
                  {loading ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}
                </button>
              </div>
            </div>

            <StepOptionsPanel step="start" variant="compact" />

            {/* 示例灵感 - 卡片式 */}
            <div>
              <div className="text-xs text-theme-sub mb-2.5 flex items-center gap-1.5">
                <Zap size={12} className="text-indigo-500" /> 试试这些爆款灵感
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {examples.map((ex) => (
                  <button
                    key={ex.text}
                    className="text-left p-2.5 rounded-xl border border-panel-border bg-panel-bg text-theme-main hover:border-indigo-500/30 hover:bg-indigo-500/5 hover:text-indigo-500 transition-all flex items-start gap-2 group"
                    onClick={() => start(ex.text)}
                    disabled={loading}
                  >
                    <span className="text-base shrink-0">{ex.icon}</span>
                    <span className="text-xs leading-relaxed group-hover:font-medium">{ex.text}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : tab === 'script' ? (
          <div className="space-y-4 animate-fade-up">
            <p className="text-sm text-theme-sub">
              粘贴或上传完整剧本文本，编剧将直接拆解为符合工业化标准的分镜剧情脚本。
            </p>
            <textarea
              className="w-full h-40 px-4 py-3 rounded-xl bg-canvas-bg border border-panel-border/60 text-sm text-theme-main resize-none outline-none focus:border-indigo-500/50 transition-all placeholder:text-theme-hint"
              placeholder="在此粘贴剧本文本...&#10;&#10;示例：&#10;第一场  夜  皇宫大殿&#10;林萧跪在金砖地上，拳头紧握...&#10;林萧：陛下，臣冤枉！"
              value={scriptText}
              onChange={(e) => setScriptText(e.target.value)}
              disabled={loading}
            />
            <ScriptUploadStats text={scriptText} />
            <input
              ref={fileInputRef}
              type="file"
              accept=".txt,.md,.text,.docx,.pdf"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleFile(f);
              }}
            />
            <div className="flex flex-col sm:flex-row gap-3">
              <button
                className="flex-1 px-4 py-2.5 rounded-xl bg-panel-bg border border-panel-border hover:border-indigo-500/30 hover:bg-indigo-500/5 transition-all text-sm text-theme-main flex items-center justify-center gap-2"
                onClick={() => fileInputRef.current?.click()}
                disabled={loading}
              >
                <Upload size={16} className="text-indigo-500" />
                上传剧本文件
              </button>
              <button
                className="flex-1 btn-primary text-sm py-2.5"
                onClick={handleStartScript}
                disabled={loading || !scriptText.trim()}
              >
                {loading ? <Loader2 size={14} className="animate-spin" /> : <PenLine size={14} />}
                <span>开始拆解剧本</span>
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-4 animate-fade-up">
            <div className="flex items-start gap-2 p-3 rounded-xl bg-indigo-500/5 border border-indigo-500/20">
              <BookText size={14} className="text-indigo-500 shrink-0 mt-0.5" />
              <p className="text-xs text-theme-sub leading-relaxed">
                粘贴或上传小说原文，AI 剧本架构师将自动删减压缩、重组为短剧节奏的结构化大纲，再进入编剧拆解流程。
              </p>
            </div>
            <textarea
              className="w-full h-48 px-4 py-3 rounded-xl bg-canvas-bg border border-panel-border/60 text-sm text-theme-main resize-none outline-none focus:border-indigo-500/50 transition-all placeholder:text-theme-hint"
              placeholder="在此粘贴小说原文...&#10;&#10;支持任意题材：都市、穿越、重生、甜宠、悬疑、玄幻等。&#10;建议提供 2000 字以上的小说片段以获得更好的改编效果。"
              value={novelText}
              onChange={(e) => setNovelText(e.target.value)}
              disabled={loading}
            />
            <ScriptUploadStats text={novelText} />
            <input
              ref={novelFileInputRef}
              type="file"
              accept=".txt,.md,.text,.docx,.pdf"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleNovelFile(f);
              }}
            />
            <div className="flex flex-col sm:flex-row gap-3">
              <button
                className="flex-1 px-4 py-2.5 rounded-xl bg-panel-bg border border-panel-border hover:border-indigo-500/30 hover:bg-indigo-500/5 transition-all text-sm text-theme-main flex items-center justify-center gap-2"
                onClick={() => novelFileInputRef.current?.click()}
                disabled={loading}
              >
                <Upload size={16} className="text-indigo-500" />
                上传小说文件
              </button>
              <button
                className="flex-1 btn-primary text-sm py-2.5"
                onClick={handleStartNovel}
                disabled={loading || !novelText.trim()}
              >
                {loading ? <Loader2 size={14} className="animate-spin" /> : <BookText size={14} />}
                <span>开始改编小说</span>
              </button>
            </div>
          </div>
        )}
      </div>

      {/* 功能亮点 */}
      <div className="flex items-center justify-center gap-5 text-xs text-theme-hint">
        <span className="flex items-center gap-1.5"><Sparkles size={13} className="text-indigo-500" /> AI 自动分镜</span>
        <span className="flex items-center gap-1.5"><ImageIcon size={13} className="text-violet-500" /> 角色/场景生图</span>
        <span className="flex items-center gap-1.5"><Film size={13} className="text-pink-500" /> 视频生成</span>
      </div>
    </div>
  );
}

export function ScriptUploadStats({ text }: { text: string }) {
  if (!text.trim()) return null;
  const chars = text.length;
  const lines = text.split(/\n/).filter((l) => l.trim()).length;
  const estimatedMinutes = Math.ceil(chars / 300);
  return (
    <div className="flex flex-wrap gap-2 text-xs text-theme-sub">
      <span className="px-2 py-1 rounded-lg bg-canvas-bg border border-panel-border/50">字数：{chars}</span>
      <span className="px-2 py-1 rounded-lg bg-canvas-bg border border-panel-border/50">行数：{lines}</span>
      <span className="px-2 py-1 rounded-lg bg-canvas-bg border border-panel-border/50">预估时长：约 {estimatedMinutes} 分钟</span>
      {chars > 5000 && (
        <span className="px-2 py-1 rounded-lg bg-warning/10 text-warning border border-warning/30">
          文本较长，将自动分批拆解
        </span>
      )}
    </div>
  );
}

export function ParameterPendingPanel() {
  const { globalParams, setGlobalParam, confirmParameters, loading, selectedLlmModel, setSelectedLlmModel } = useAgentStore();

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div className="text-center">
        <h3 className="text-2xl font-bold text-theme-main mb-2">确认全局创作参数</h3>
        <p className="text-sm text-theme-sub">
          AI 已根据你的输入推荐以下参数，这些参数将作为整部短剧的全局约束。
        </p>
      </div>

      <div className="glass rounded-2xl border border-panel-border/60 shadow-soft p-5">
        <div className="mb-5 pb-5 border-b border-panel-border/50">
          <LlmModelSelector
            selected={selectedLlmModel}
            onSelect={setSelectedLlmModel}
            disabled={loading}
          />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {GLOBAL_PARAM_DEFINITIONS.map((def) => (
            <div key={def.key} className="space-y-1.5">
              <label className="text-xs text-theme-sub flex items-center gap-1">
                {def.label}
                {def.editable === false && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-indigo-500/10 text-indigo-500">自动</span>
                )}
              </label>
              {def.type === 'select' ? (
                <select
                  className="w-full text-sm bg-canvas-bg border border-panel-border/60 rounded-xl px-3 py-2 text-theme-main outline-none focus:border-indigo-500/50 transition-all disabled:opacity-50"
                  value={globalParams[def.key] ?? ''}
                  onChange={(e) => setGlobalParam(def.key, e.target.value)}
                  disabled={loading}
                >
                  {def.options?.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              ) : (
                <input
                  type="text"
                  className="w-full text-sm bg-canvas-bg border border-panel-border/60 rounded-xl px-3 py-2 text-theme-main outline-none focus:border-indigo-500/50 transition-all disabled:opacity-50"
                  value={globalParams[def.key] ?? ''}
                  onChange={(e) => setGlobalParam(def.key, e.target.value)}
                  disabled={def.editable === false || loading}
                />
              )}
            </div>
          ))}
        </div>

        <button
          className="w-full btn-primary text-sm py-2.5 mt-6"
          onClick={confirmParameters}
          disabled={loading}
        >
          {loading ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle size={14} />}
          <span>确认参数，开始创作</span>
        </button>
      </div>
    </div>
  );
}
