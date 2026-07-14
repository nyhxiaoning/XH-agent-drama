/**
 * P4: PlanningPanel + ScreenwriterPanel + DialogueLine + FeedbackBubble
 * #3: 对白编辑器输入框尺寸优化
 * #9: 编剧编辑自动保存（localStorage 防丢失）
 * #11: 成本预估
 * #16: 键盘快捷键
 */
import { useState, useEffect, useMemo, useRef } from 'react';
import {
  Loader2, CheckCircle, MapPin, PenLine, BookOpen, X,
  AlertCircle, Maximize2, Minimize2, RefreshCw, Pencil, Save,
} from 'lucide-react';
import type {
  ShortDramaScript, ShortDramaScreenwriter,
} from '@/types';
import { useAgentStore } from '@/store/agent';
import { StepOptionsPanel, SkipButton, CostEstimateBadge } from '../Controls';
import { DRAMA_MAX_RETRIES } from '../constants';

export function FeedbackBubble({
  message, retryCount, onRetry, onAccept, onAbort, loading,
}: {
  message?: string;
  retryCount?: number;
  onRetry?: () => void;
  onAccept?: () => void;
  onAbort?: () => void;
  loading?: boolean;
}) {
  const [expanded, setExpanded] = useState(true);
  if (!message) return null;
  const reachedLimit = (retryCount || 0) >= DRAMA_MAX_RETRIES;
  const hasActions = reachedLimit && (onRetry || onAccept || onAbort);
  return (
    <div className="card p-3 border-l-4 border-warning bg-warning/5 shadow-soft space-y-1">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-warning text-xs font-bold">
          <AlertCircle size={14} />
          <span>导演质检反馈{retryCount ? `（第 ${retryCount} 次重试）` : ''}</span>
        </div>
        <button className="text-theme-hint hover:text-theme-main" onClick={() => setExpanded((v) => !v)}>
          {expanded ? <Minimize2 size={10} /> : <Maximize2 size={10} />}
        </button>
      </div>
      {expanded && (
        <>
          <div className="text-xs text-theme-main whitespace-pre-line leading-relaxed">{message}</div>
          {hasActions && (
            <div className="flex flex-wrap gap-2 pt-2 border-t border-warning/20">
              {onRetry && (
                <button
                  className="px-3 py-1.5 rounded-full text-[11px] btn-primary disabled:opacity-50"
                  onClick={onRetry}
                  disabled={loading}
                  title="重试本阶段（不计入自动重试次数上限）"
                >
                  <RefreshCw size={11} className="inline mr-1" />重试一次
                </button>
              )}
              {onAccept && (
                <button
                  className="px-3 py-1.5 rounded-full text-[11px] bg-theme-input text-theme-main hover:bg-panel-hover border border-panel-border disabled:opacity-50"
                  onClick={onAccept}
                  disabled={loading}
                  title="接受当前结果，进入下一阶段"
                >
                  <CheckCircle size={11} className="inline mr-1" />接受当前结果
                </button>
              )}
              {onAbort && (
                <button
                  className="px-3 py-1.5 rounded-full text-[11px] text-error hover:bg-error/10 border border-error/30 disabled:opacity-50"
                  onClick={onAbort}
                  disabled={loading}
                  title="放弃本次结果，回到起点"
                >
                  <X size={11} className="inline mr-1" />放弃这次结果
                </button>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function PlanningPanel({
  script, screenwriter, feedback, retryCount, onConfirm, onSkip, loading, onRetry, onAccept, onAbort,
}: {
  script?: ShortDramaScript;
  screenwriter?: ShortDramaScreenwriter;
  feedback?: string;
  retryCount?: number;
  onConfirm: () => void;
  onSkip: () => void;
  loading: boolean;
  onRetry?: () => void;
  onAccept?: () => void;
  onAbort?: () => void;
}) {
  const sp = screenwriter?.screenplay;
  return (
    <div className="space-y-4">
      {feedback && <FeedbackBubble message={feedback} retryCount={retryCount} onRetry={onRetry} onAccept={onAccept} onAbort={onAbort} loading={loading} />}
      {!sp && script && (
        <div className="card p-3 shadow-soft space-y-1">
          <div className="text-sm font-bold text-theme-main flex items-center gap-2">
            <BookOpen size={14} className="text-teal-600" />
            {script.project_title}
          </div>
          <div className="text-xs text-theme-sub">{script.genre} · 正在编剧拆解...</div>
        </div>
      )}
      {sp ? (
        <ScreenwriterPanel
          screenwriter={screenwriter}
          rawScriptText={script?.raw_script_text}
          onConfirm={onConfirm}
          onSkip={onSkip}
          loading={loading}
        />
      ) : (
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <Loader2 size={24} className="animate-spin text-teal-600 mb-3" />
          <p className="text-sm text-theme-sub">编剧正在拆解剧本，预计需要 1-3 分钟，请耐心等待...</p>
        </div>
      )}
    </div>
  );
}

export function ScreenwriterPanel({
  screenwriter, rawScriptText, onConfirm, onSkip, loading
}: {
  screenwriter?: ShortDramaScreenwriter;
  rawScriptText?: string;
  onConfirm: () => void;
  onSkip: () => void;
  loading: boolean;
}) {
  const sp = screenwriter?.screenplay;
  const [editingEpisode, setEditingEpisode] = useState<number | null>(null);
  const [showSource, setShowSource] = useState(false);
  const [draft, setDraft] = useState<ShortDramaScreenwriter | undefined>(screenwriter);
  const [autoSaved, setAutoSaved] = useState(false);
  const autoSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setDraft(screenwriter);
  }, [screenwriter]);

  const isDraft = useMemo(
    () => JSON.stringify(draft) !== JSON.stringify(screenwriter),
    [draft, screenwriter]
  );

  // #9: 自动保存到 localStorage（防丢失）
  const sessionKey = useAgentStore.getState().session?.id;
  const storageKey = `screenwriter_draft_${sessionKey || 'tmp'}`;

  // 启动时尝试从 localStorage 恢复草稿
  useEffect(() => {
    if (!screenwriter) return;
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved) {
        const parsed = JSON.parse(saved);
        // 只有当 saved 与 screenwriter 有差异时才恢复
        if (JSON.stringify(parsed) !== JSON.stringify(screenwriter)) {
          setDraft(parsed);
          setAutoSaved(true);
        }
      }
    } catch {
      // ignore
    }
  }, [storageKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // 编辑后 debounce 自动保存到 localStorage
  useEffect(() => {
    if (!draft || !isDraft) return;
    if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current);
    autoSaveTimerRef.current = setTimeout(() => {
      try {
        localStorage.setItem(storageKey, JSON.stringify(draft));
        setAutoSaved(true);
      } catch {
        // ignore
      }
    }, 1500);
    return () => {
      if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current);
    };
  }, [draft, isDraft, storageKey]);

  if (!sp) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <Loader2 size={24} className="animate-spin text-teal-600 mb-3" />
        <p className="text-sm text-theme-sub">编剧正在拆解剧本，预计需要 1-3 分钟，请耐心等待...</p>
      </div>
    );
  }

  const updateScene = (episodeNum: number, sceneId: string, patch: Partial<ShortDramaScreenwriter['screenplay']['episodes'][0]['scenes'][0]>) => {
    if (!draft) return;
    const newDraft: ShortDramaScreenwriter = {
      screenplay: {
        ...draft.screenplay,
        episodes: draft.screenplay.episodes.map((ep) =>
          ep.episode_num !== episodeNum
            ? ep
            : {
                ...ep,
                scenes: ep.scenes.map((s) => (s.scene_id === sceneId ? { ...s, ...patch } : s)),
              }
        ),
      },
    };
    setDraft(newDraft);
  };

  const updateDialogue = (episodeNum: number, sceneId: string, idx: number, patch: Partial<{ character: string; line: string; emotion: string }>) => {
    if (!draft) return;
    const newDraft: ShortDramaScreenwriter = {
      screenplay: {
        ...draft.screenplay,
        episodes: draft.screenplay.episodes.map((ep) =>
          ep.episode_num !== episodeNum
            ? ep
            : {
                ...ep,
                scenes: ep.scenes.map((s) =>
                  s.scene_id !== sceneId
                    ? s
                    : {
                        ...s,
                        dialogues: s.dialogues.map((d, i) => (i === idx ? { ...d, ...patch } : d)),
                      }
                ),
              }
        ),
      },
    };
    setDraft(newDraft);
  };

  const addDialogue = (episodeNum: number, sceneId: string) => {
    if (!draft) return;
    const newDraft: ShortDramaScreenwriter = {
      screenplay: {
        ...draft.screenplay,
        episodes: draft.screenplay.episodes.map((ep) =>
          ep.episode_num !== episodeNum
            ? ep
            : {
                ...ep,
                scenes: ep.scenes.map((s) =>
                  s.scene_id !== sceneId
                    ? s
                    : { ...s, dialogues: [...s.dialogues, { character: '', line: '', emotion: '' }] }
                ),
              }
        ),
      },
    };
    setDraft(newDraft);
  };

  const removeDialogue = (episodeNum: number, sceneId: string, idx: number) => {
    if (!draft) return;
    const newDraft: ShortDramaScreenwriter = {
      screenplay: {
        ...draft.screenplay,
        episodes: draft.screenplay.episodes.map((ep) =>
          ep.episode_num !== episodeNum
            ? ep
            : {
                ...ep,
                scenes: ep.scenes.map((s) =>
                  s.scene_id !== sceneId
                    ? s
                    : { ...s, dialogues: s.dialogues.filter((_, i) => i !== idx) }
                ),
              }
        ),
      },
    };
    setDraft(newDraft);
  };

  const episodesList = useMemo(
    () => (
      <>
        {draft?.screenplay.episodes.map((ep) => (
          <div key={ep.episode_num} className="card p-4 space-y-3 shadow-soft">
            <div className="flex items-center justify-between">
              <div className="text-sm font-semibold text-theme-main">第 {ep.episode_num} 集 · {ep.logline}</div>
              <button
                className="text-[11px] text-theme-sub hover:text-teal-600 flex items-center gap-1"
                onClick={() => setEditingEpisode(editingEpisode === ep.episode_num ? null : ep.episode_num)}
              >
                {editingEpisode === ep.episode_num ? '完成编辑' : '编辑本集'}
                <Pencil size={10} />
              </button>
            </div>
            {ep.scenes.map((scene) => (
              <div key={scene.scene_id} className="bg-canvas-bg rounded-xl p-3 text-sm space-y-2">
                <div className="flex items-center gap-2 text-theme-main">
                  <MapPin size={12} />
                  {editingEpisode === ep.episode_num ? (
                    <>
                      <input
                        className="bg-panel-bg border border-panel-border rounded px-2 py-0.5 text-xs flex-1"
                        value={scene.location}
                        onChange={(e) => updateScene(ep.episode_num, scene.scene_id, { location: e.target.value })}
                      />
                      <input
                        className="bg-panel-bg border border-panel-border rounded px-2 py-0.5 text-xs w-16"
                        value={scene.time}
                        onChange={(e) => updateScene(ep.episode_num, scene.scene_id, { time: e.target.value })}
                      />
                    </>
                  ) : (
                    <>
                      {scene.location} · {scene.time}
                    </>
                  )}
                  {scene.emotion_intensity != null && (
                    <span className="ml-auto text-xs text-theme-sub">情绪 {scene.emotion_intensity}</span>
                  )}
                </div>
                {editingEpisode === ep.episode_num ? (
                  <textarea
                    className="w-full bg-panel-bg border border-panel-border rounded-lg px-2 py-1.5 text-xs text-theme-main resize-none outline-none focus:border-teal-600/50"
                    rows={3}
                    value={scene.action_description}
                    onChange={(e) => updateScene(ep.episode_num, scene.scene_id, { action_description: e.target.value })}
                  />
                ) : (
                  <div className="text-theme-main leading-relaxed">{scene.action_description}</div>
                )}
                <div className="space-y-1.5 pt-2 border-t border-panel-border/50">
                  {scene.dialogues.map((d, i) => (
                    <DialogueLine
                      key={i}
                      dialogue={d}
                      editing={editingEpisode === ep.episode_num}
                      onChange={(patch) => updateDialogue(ep.episode_num, scene.scene_id, i, patch)}
                      onRemove={() => removeDialogue(ep.episode_num, scene.scene_id, i)}
                    />
                  ))}
                  {editingEpisode === ep.episode_num && (
                    <button
                      className="text-[11px] text-teal-600 hover:underline flex items-center gap-1"
                      onClick={() => addDialogue(ep.episode_num, scene.scene_id)}
                    >
                      <PenLine size={10} /> 添加对白
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        ))}

        <div className="flex justify-end gap-2 pt-1 items-center">
          <SkipButton onClick={onSkip} loading={loading} label="跳过，进入资产设定" />
          <button className="btn-primary text-xs" onClick={onConfirm} disabled={loading}>
            {loading ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle size={12} />}
            <span>确认参数，进入资产设定</span>
          </button>
          <CostEstimateBadge step="asset" />
        </div>
      </>
    ),
    [draft, editingEpisode, loading, onConfirm, onSkip]
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold text-theme-main flex items-center gap-2">
          <PenLine size={14} className="text-teal-600" />
          编剧 · 分场分幕剧本
        </h3>
        <div className="flex items-center gap-2">
          <span className="px-2 py-0.5 rounded-lg bg-teal-600/10 text-teal-600 text-xs">{sp.total_episodes} 集</span>
          {isDraft && (
            <span className="px-2 py-0.5 rounded-lg bg-warning/10 text-warning text-xs flex items-center gap-1">
              <Pencil size={10} /> 已修改{autoSaved ? '·已自动保存' : '未保存'}
            </span>
          )}
        </div>
      </div>

      {rawScriptText && (
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowSource((v) => !v)}
            className={`text-[11px] px-2.5 py-1.5 rounded-lg border transition-all flex items-center gap-1.5 ${
              showSource
                ? 'bg-teal-600 text-white border-teal-600'
                : 'bg-panel-bg border-panel-border text-theme-sub hover:text-theme-main'
            }`}
          >
            <BookOpen size={11} />
            {showSource ? '隐藏原文' : '对照原文'}
          </button>
          {showSource && (
            <span className="text-[10px] text-theme-hint">右侧为编剧拆解结果，可对照左侧原文进行核对</span>
          )}
        </div>
      )}

      {showSource && rawScriptText && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <div className="card p-4 space-y-2 border-l-4 border-teal-600/50 max-h-[70vh] overflow-y-auto">
            <div className="text-xs font-bold text-theme-main flex items-center gap-2 sticky top-0 bg-theme-card py-1">
              <BookOpen size={12} className="text-emerald-500" />
              上传原文
            </div>
            <div className="text-xs text-theme-main leading-relaxed whitespace-pre-line font-mono">
              {rawScriptText}
            </div>
          </div>
          <div className="space-y-4">
            <StepOptionsPanel step="planning" variant="compact" showTemplate={false} />
            {episodesList}
          </div>
        </div>
      )}

      {!showSource && (
        <>
          <StepOptionsPanel step="planning" variant="compact" showTemplate={false} />
          {episodesList}
        </>
      )}
    </div>
  );
}

export function DialogueLine({
  dialogue, editing, onChange, onRemove
}: {
  dialogue: { character: string; line: string; emotion: string };
  editing: boolean;
  onChange: (patch: Partial<{ character: string; line: string; emotion: string }>) => void;
  onRemove: () => void;
}) {
  const len = dialogue.line.length;
  const overLimit = len > 20;
  if (!editing) {
    return (
      <div className="flex gap-2">
        <span className="text-teal-600 font-medium shrink-0">{dialogue.character}（{dialogue.emotion}）：</span>
        <span className="text-theme-main">{dialogue.line}</span>
      </div>
    );
  }
  return (
    <div className="space-y-1">
      <div className="flex gap-2 items-start">
        <input
          className="w-28 bg-panel-bg border border-panel-border rounded px-2 py-0.5 text-xs"
          value={dialogue.character}
          placeholder="角色"
          onChange={(e) => onChange({ character: e.target.value })}
        />
        <input
          className="w-24 bg-panel-bg border border-panel-border rounded px-2 py-0.5 text-xs"
          value={dialogue.emotion}
          placeholder="情绪"
          onChange={(e) => onChange({ emotion: e.target.value })}
        />
        <button
          className="text-theme-hint hover:text-error"
          onClick={onRemove}
          title="删除"
        >
          <X size={12} />
        </button>
      </div>
      <div className="relative">
        <textarea
          className="w-full bg-panel-bg border border-panel-border rounded-lg px-2 py-1 text-xs text-theme-main resize-none outline-none focus:border-teal-600/50"
          rows={2}
          value={dialogue.line}
          placeholder="对白内容"
          onChange={(e) => onChange({ line: e.target.value })}
        />
        <span className={`absolute bottom-1 right-2 text-[10px] ${overLimit ? 'text-error' : 'text-theme-hint'}`}>
          {len}/20
        </span>
      </div>
    </div>
  );
}
