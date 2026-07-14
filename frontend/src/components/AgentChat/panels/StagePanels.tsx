/**
 * P4: AssetPanel + AssetsPanel + AssetCard + FinalizedPanel + ProductionPanel
 * #4: 分镜卡片折叠 final_video_prompt
 * #11: 成本预估
 * #12: 资产卡大图预览 Lightbox
 * #13: 分镜拖拽排序（HTML5 drag-and-drop）
 * #14: FinalizedPanel 增强 - 缩略图墙
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Loader2, Lock, Unlock, Image as ImageIcon, CheckCircle,
  RefreshCw, ArrowRight, Sparkles, LayoutGrid, Clapperboard,
  ChevronDown, ChevronUp, Eye, X, GripVertical,
} from 'lucide-react';
import { useAgentStore, type AgentStepKey } from '@/store/agent';
import type {
  ShortDramaAssets, ShortDramaCharacterData, ShortDramaSceneData,
  ShortDramaStoryboard, ShortDramaVideos, LockedAsset,
} from '@/types';
import { StepOptionsPanel, SkipButton, CostEstimateBadge } from '../Controls';
import { FeedbackBubble } from './PlanningPanel';

/** #12: 资产大图预览 Lightbox */
function AssetLightbox({ url, title, onClose }: { url: string; title: string; onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div className="relative max-w-3xl max-h-[85vh] w-full" onClick={(e) => e.stopPropagation()}>
        <img src={url} alt={title} className="w-full h-full object-contain rounded-xl" />
        <div className="absolute top-2 left-2 right-2 flex items-center justify-between">
          <span className="text-sm text-white bg-black/50 rounded-lg px-2 py-1">{title}</span>
          <button
            className="w-8 h-8 rounded-full bg-black/50 text-white flex items-center justify-center hover:bg-black/70"
            onClick={onClose}
          >
            <X size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}

export function AssetCard({ title, subtitle, desc, prompt, thumbnailUrl, selected, onClick }: {
  title: string; subtitle: string; desc: string; prompt: string; thumbnailUrl?: string; selected: boolean; onClick: () => void;
}) {
  const [lightboxOpen, setLightboxOpen] = useState(false);
  return (
    <>
      <div
        onClick={onClick}
        className={`relative rounded-xl cursor-pointer transition-all shadow-soft overflow-hidden ${
          selected
            ? 'border-2 border-indigo-500 bg-indigo-500/10'
            : 'border border-panel-border bg-panel-bg hover:border-indigo-500/30 hover:-translate-y-0.5'
        }`}
      >
        <div className="absolute top-2 right-2 z-10 flex items-center gap-1">
          {/* #12: 预览大图按钮 */}
          {thumbnailUrl && (
            <button
              className="w-6 h-6 rounded-full bg-black/40 text-white flex items-center justify-center hover:bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity"
              onClick={(e) => {
                e.stopPropagation();
                setLightboxOpen(true);
              }}
              title="预览大图"
            >
              <Eye size={11} />
            </button>
          )}
          {selected ? <Lock size={12} className="text-indigo-500" /> : <Unlock size={12} className="text-theme-hint" />}
        </div>
        {thumbnailUrl ? (
          <div className="aspect-video w-full bg-canvas-bg overflow-hidden group">
            <img src={thumbnailUrl} alt={title} className="w-full h-full object-cover" />
          </div>
        ) : null}
        <div className="p-3">
          <div className="text-sm font-semibold text-theme-main">{title}</div>
          <div className="text-xs text-theme-sub mb-1">{subtitle}</div>
          {desc && <div className="text-sm text-theme-main mb-1 line-clamp-2">{desc}</div>}
          <div className="text-[11px] text-theme-sub font-mono line-clamp-2 bg-canvas-bg rounded-lg p-1.5">
            {prompt}
          </div>
        </div>
      </div>
      {/* #12: Lightbox */}
      {lightboxOpen && thumbnailUrl && (
        <AssetLightbox url={thumbnailUrl} title={title} onClose={() => setLightboxOpen(false)} />
      )}
    </>
  );
}

export function AssetsPanel({
  assets, selectedChars, selectedScenes, onToggleChar, onToggleScene, onSelectAll, onLock, onSkip, loading,
  step = 'asset',
}: {
  assets: ShortDramaAssets;
  selectedChars: string[];
  selectedScenes: string[];
  onToggleChar: (id: string) => void;
  onToggleScene: (id: string) => void;
  onSelectAll: () => void;
  onLock: () => void;
  onSkip: () => void;
  loading: boolean;
  step?: AgentStepKey;
}) {
  const { session } = useAgentStore();
  const lockedById = new Map<string, LockedAsset>();
  (session?.locked_assets || []).forEach((a) => {
    if (a.char_id) lockedById.set(a.char_id, a);
    if (a.scene_id) lockedById.set(a.scene_id, a);
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold text-theme-main flex items-center gap-2">
          <ImageIcon size={14} className="text-indigo-500" />
          角色与场景资产
        </h3>
        <button className="btn-secondary text-xs px-2 py-1" onClick={onSelectAll}>
          全选
        </button>
      </div>
      <StepOptionsPanel step={step} variant="compact" showTemplate={false} />
      <p className="text-sm text-theme-sub">
        请选择需要锁定的角色与场景，锁定后将自动生成概念图并保存到资产库。
      </p>

      <div>
        <div className="text-xs font-semibold text-theme-main uppercase tracking-wider mb-2">角色</div>
        {/* #5: 移动端适配 - grid 断点 */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {assets.characters.map((char) => (
            <AssetCard
              key={char.char_id}
              title={char.name}
              subtitle={char.role}
              desc={char.visual_anchor}
              prompt={char.base_prompt}
              thumbnailUrl={lockedById.get(char.char_id)?.asset_file_url}
              selected={selectedChars.includes(char.char_id)}
              onClick={() => onToggleChar(char.char_id)}
            />
          ))}
        </div>
      </div>

      <div>
        <div className="text-xs font-semibold text-theme-main uppercase tracking-wider mb-2">场景</div>
        {/* #5: 移动端适配 */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {assets.scenes.map((scene) => (
            <AssetCard
              key={scene.scene_id}
              title={scene.name}
              subtitle="场景"
              desc=""
              prompt={scene.base_prompt}
              thumbnailUrl={lockedById.get(scene.scene_id)?.asset_file_url}
              selected={selectedScenes.includes(scene.scene_id)}
              onClick={() => onToggleScene(scene.scene_id)}
            />
          ))}
        </div>
      </div>

      <div className="flex justify-end gap-2 pt-1 items-center">
        <SkipButton onClick={onSkip} loading={loading} label="跳过生图，直接进入拍摄制作" />
        <button className="btn-primary text-xs px-2 py-1" onClick={onLock} disabled={loading || (selectedChars.length === 0 && selectedScenes.length === 0)}>
          {loading ? <Loader2 size={12} className="animate-spin" /> : <Lock size={12} />}
          <span>锁定并生图</span>
        </button>
        <CostEstimateBadge step="asset" />
      </div>
    </div>
  );
}

export function AssetPanel({
  character, scene, selectedChars, selectedScenes, feedback, retryCount,
  onToggleChar, onToggleScene, onSelectAll, onLock, onSkip, loading, onRetry, onAccept, onAbort,
}: {
  character?: ShortDramaCharacterData | ShortDramaAssets;
  scene?: ShortDramaSceneData | ShortDramaAssets;
  selectedChars: string[];
  selectedScenes: string[];
  feedback?: string;
  retryCount?: number;
  onToggleChar: (id: string) => void;
  onToggleScene: (id: string) => void;
  onSelectAll: () => void;
  onLock: () => void;
  onSkip: () => void;
  loading: boolean;
  onRetry?: () => void;
  onAccept?: () => void;
  onAbort?: () => void;
}) {
  const assets: ShortDramaAssets = {
    characters: ((character as any)?.characters || []) as ShortDramaAssets['characters'],
    scenes: ((scene as any)?.scenes || []) as ShortDramaAssets['scenes'],
    props: ((scene as any)?.props || []) as ShortDramaAssets['props'],
    character_relations: ((character as any)?.character_relations || []) as ShortDramaAssets['character_relations'],
  };
  return (
    <div className="space-y-4">
      {feedback && <FeedbackBubble message={feedback} retryCount={retryCount} onRetry={onRetry} onAccept={onAccept} onAbort={onAbort} loading={loading} />}
      <AssetsPanel
        assets={assets}
        selectedChars={selectedChars}
        selectedScenes={selectedScenes}
        onToggleChar={onToggleChar}
        onToggleScene={onToggleScene}
        onSelectAll={onSelectAll}
        onLock={onLock}
        onSkip={onSkip}
        loading={loading}
        step="asset"
      />
    </div>
  );
}

export function ProductionPanel({
  storyboard, videos, feedback, retryCount, onGenerate, onEnterCanvas, loading, onRetry, onAccept, onAbort,
}: {
  storyboard?: ShortDramaStoryboard;
  videos?: ShortDramaVideos;
  feedback?: string;
  retryCount?: number;
  onGenerate: () => void;
  onEnterCanvas: () => void;
  loading: boolean;
  onRetry?: () => void;
  onAccept?: () => void;
  onAbort?: () => void;
}) {
  const hasStoryboards = storyboard && storyboard.storyboards && storyboard.storyboards.length > 0;
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  // #4: 控制每张分镜卡片的 prompt 折叠状态
  const [expandedPrompts, setExpandedPrompts] = useState<Set<string>>(new Set());
  // #13: 拖拽排序
  const [orderedStoryboards, setOrderedStoryboards] = useState(storyboard?.storyboards || []);
  const [dragIndex, setDragIndex] = useState<number | null>(null);

  useEffect(() => {
    if (storyboard?.storyboards) {
      setSelectedIds(new Set(storyboard.storyboards.map((sb) => sb.storyboard_id)));
      setOrderedStoryboards(storyboard.storyboards);
    }
  }, [storyboard?.storyboards?.length]);

  const toggleId = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // #4: 切换 prompt 折叠
  const togglePrompt = (id: string) => {
    setExpandedPrompts((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // #13: 拖拽排序
  const handleDragStart = (idx: number) => setDragIndex(idx);
  const handleDragOver = (e: React.DragEvent, idx: number) => {
    e.preventDefault();
    if (dragIndex === null || dragIndex === idx) return;
    setOrderedStoryboards((prev) => {
      const next = [...prev];
      const [moved] = next.splice(dragIndex, 1);
      next.splice(idx, 0, moved);
      return next;
    });
    setDragIndex(idx);
  };
  const handleDragEnd = () => setDragIndex(null);

  return (
    <div className="space-y-4">
      {feedback && <FeedbackBubble message={feedback} retryCount={retryCount} onRetry={onRetry} onAccept={onAccept} onAbort={onAbort} loading={loading} />}
      <StepOptionsPanel step="production" variant="compact" showTemplate={false} />

      {hasStoryboards ? (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-theme-main flex items-center gap-2">
              <Clapperboard size={14} className="text-indigo-500" />
              导演分镜脚本
              <span className="text-[10px] text-theme-hint font-normal">拖拽可排序</span>
            </h3>
            <div className="flex items-center gap-2">
              <button
                className="text-[11px] text-theme-sub hover:text-indigo-500"
                onClick={() => setSelectedIds(new Set(orderedStoryboards.map((sb) => sb.storyboard_id)))}
              >
                全选
              </button>
              <button
                className="text-[11px] text-theme-sub hover:text-indigo-500"
                onClick={() => setSelectedIds(new Set())}
              >
                清空
              </button>
            </div>
          </div>
          {/* #5: 移动端适配 + #13: 拖拽排序 */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {orderedStoryboards.map((sb, idx) => {
              const selected = selectedIds.has(sb.storyboard_id);
              const promptExpanded = expandedPrompts.has(sb.storyboard_id);
              return (
                <div
                  key={sb.storyboard_id}
                  draggable
                  onDragStart={() => handleDragStart(idx)}
                  onDragOver={(e) => handleDragOver(e, idx)}
                  onDragEnd={handleDragEnd}
                  onClick={() => toggleId(sb.storyboard_id)}
                  className={`card p-3 space-y-2 shadow-soft cursor-pointer transition-all ${
                    selected ? 'border-indigo-500 bg-indigo-500/5' : 'border-panel-border'
                  } ${dragIndex === idx ? 'opacity-50' : ''}`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      {/* #13: 拖拽手柄 */}
                      <GripVertical size={12} className="text-theme-hint cursor-grab active:cursor-grabbing" />
                      <div className={`w-4 h-4 rounded border flex items-center justify-center ${selected ? 'bg-indigo-500 border-indigo-500' : 'border-panel-border'}`}>
                        {selected && <CheckCircle size={10} className="text-white" />}
                      </div>
                      <span className="text-sm font-semibold text-theme-main">分镜 {idx + 1}</span>
                    </div>
                    <span className="text-xs text-theme-sub">{sb.duration_seconds}s</span>
                  </div>
                  <div className="flex flex-wrap gap-2 text-xs text-theme-main">
                    <span className="px-1.5 py-0.5 rounded bg-canvas-bg">{sb.shot_type}</span>
                    <span className="px-1.5 py-0.5 rounded bg-canvas-bg">{sb.camera_movement}</span>
                    {sb.composition && <span className="px-1.5 py-0.5 rounded bg-canvas-bg">{sb.composition}</span>}
                  </div>
                  <div className="text-sm text-theme-main leading-relaxed line-clamp-3">{sb.visual_description}</div>
                  {/* #4: 可折叠的 final_video_prompt */}
                  {sb.final_video_prompt && (
                    <div>
                      <button
                        className="text-[10px] text-theme-sub hover:text-indigo-500 flex items-center gap-1"
                        onClick={(e) => {
                          e.stopPropagation();
                          togglePrompt(sb.storyboard_id);
                        }}
                      >
                        {promptExpanded ? <ChevronUp size={9} /> : <ChevronDown size={9} />}
                        {promptExpanded ? '收起' : '展开'}视频 Prompt
                      </button>
                      {promptExpanded && (
                        <div className="text-[11px] text-theme-sub font-mono bg-canvas-bg rounded p-1.5 mt-1">
                          {sb.final_video_prompt}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center py-10 text-center">
          <Loader2 size={24} className="animate-spin text-indigo-500 mb-3" />
          <p className="text-sm text-theme-sub">分镜与视频参数规划中，请稍候...</p>
        </div>
      )}

      <div className="card p-4 space-y-3 bg-theme-card border border-panel-border">
        <div className="text-xs text-theme-sub">已选择 {selectedIds.size} 个分镜，请选择下一步操作：</div>
        <button
          className="w-full card p-3 flex items-center gap-3 hover:border-indigo-500 hover:bg-indigo-500/5 transition-all text-left group"
          onClick={onGenerate}
          disabled={loading || selectedIds.size === 0}
        >
          <div className="w-9 h-9 rounded-lg bg-indigo-500/15 text-indigo-500 flex items-center justify-center flex-shrink-0">
            <Sparkles size={16} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-theme-main flex items-center gap-1.5">
              直接生成图片
              <ArrowRight size={11} className="text-indigo-500 opacity-0 group-hover:opacity-100 transition-opacity" />
            </div>
            <div className="text-xs text-theme-sub mt-0.5">自动生成所有角色、场景图，进入画布后可手动生成分镜和视频</div>
          </div>
        </button>
        <button
          className="w-full card p-3 flex items-center gap-3 hover:border-panel-border hover:bg-theme-hover transition-all text-left group"
          onClick={onEnterCanvas}
          disabled={loading}
        >
          <div className="w-9 h-9 rounded-lg bg-theme-elevated text-theme-sub flex items-center justify-center flex-shrink-0">
            <LayoutGrid size={16} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-theme-main flex items-center gap-1.5">
              进入画布
              <ArrowRight size={11} className="text-theme-sub opacity-0 group-hover:opacity-100 transition-opacity" />
            </div>
            <div className="text-xs text-theme-sub mt-0.5">只创建节点卡片，所有图片视频手动生成</div>
          </div>
        </button>
      </div>

      {loading && (
        <div className="flex items-center justify-center gap-2 text-xs text-theme-sub py-2">
          <Loader2 size={12} className="animate-spin" />
          <span>正在创建画布...</span>
        </div>
      )}
    </div>
  );
}

/** #14: 增强的完成面板 - 缩略图墙 */
export function FinalizedPanel({ onJump, onRestart }: { onJump: () => void; onRestart: () => void }) {
  const { session } = useAgentStore();
  const tokens = (session as any)?.token_used ?? 0;
  const title = session?.full_script?.screenplay?.project_title || session?.script_outline?.project_title || '未命名短剧';
  const episodes = session?.full_script?.screenplay?.total_episodes || 1;
  const chars = session?.character_assets?.characters || session?.character?.characters || [];
  const scenes = session?.scene_assets?.scenes || session?.scene?.scenes || [];
  const storyboards = session?.storyboard_data?.storyboards || session?.storyboard?.storyboards || [];
  const lockedAssets = session?.locked_assets || [];

  // 收集所有缩略图
  const thumbnails = lockedAssets
    .filter((a) => a.asset_file_url)
    .map((a) => ({ url: a.asset_file_url!, name: a.name || a.type }));

  return (
    <div className="h-full flex flex-col items-center justify-center text-center max-w-lg mx-auto py-6 overflow-y-auto">
      <div className="w-14 h-14 rounded-full bg-success/20 text-success flex items-center justify-center mb-3">
        <CheckCircle size={28} />
      </div>
      <h3 className="text-lg font-bold text-theme-main mb-1">短剧创作流水线已完成</h3>
          <p className="text-sm text-theme-sub mb-4">
        剧本、角色、场景、分镜和视频节点已自动创建到画布中。
      </p>

      <div className="w-full card p-4 space-y-2 text-left mb-4">
        <div className="flex justify-between text-sm"><span className="text-theme-sub">剧名</span><span className="text-theme-main font-medium">{title}</span></div>
        <div className="flex justify-between text-sm"><span className="text-theme-sub">集数</span><span className="text-theme-main font-medium">{episodes} 集</span></div>
        <div className="flex justify-between text-sm"><span className="text-theme-sub">角色/场景/分镜</span><span className="text-theme-main font-medium">{chars.length}/{scenes.length}/{storyboards.length}</span></div>
        {tokens > 0 && (
          <div className="flex justify-between text-sm"><span className="text-theme-sub">Token 消耗</span><span className="text-theme-main font-medium">~{tokens.toLocaleString()}</span></div>
        )}
      </div>

      {/* #14: 缩略图墙 */}
      {thumbnails.length > 0 && (
        <div className="w-full mb-4">
          <div className="text-xs text-theme-sub mb-2 text-left">已生成资产预览</div>
          <div className="grid grid-cols-4 sm:grid-cols-5 gap-2">
            {thumbnails.slice(0, 10).map((t, idx) => (
              <div key={idx} className="aspect-square rounded-lg overflow-hidden border border-panel-border bg-canvas-bg">
                <img src={t.url} alt={t.name} className="w-full h-full object-cover" />
              </div>
            ))}
          </div>
          {thumbnails.length > 10 && (
            <div className="text-[10px] text-theme-hint mt-1">还有 {thumbnails.length - 10} 个资产...</div>
          )}
        </div>
      )}

      <div className="flex gap-2 w-full">
        <button className="btn-secondary text-xs flex-1 justify-center" onClick={onRestart}>
          <RefreshCw size={12} />
          <span>再创作</span>
        </button>
        <button className="btn-primary text-xs flex-1 justify-center" onClick={onJump}>
          <ArrowRight size={12} />
          <span>进入画布</span>
        </button>
      </div>
    </div>
  );
}
