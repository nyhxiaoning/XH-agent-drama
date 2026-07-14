import { useEffect, useState } from 'react';
import { X, Search, Image as ImageIcon, Film, Music, User, MapPin, Package, Link2, Check, Trash2, Globe } from 'lucide-react';
import { useEditorStore } from '@/store/editor';
import { api } from '@/utils/api';
import type { Asset } from '@/types';

const TYPE_OPTIONS: { value: string; label: string; icon: React.ReactNode }[] = [
  { value: 'all', label: '全部', icon: <Package size={14} /> },
  { value: 'character', label: '角色', icon: <User size={14} /> },
  { value: 'scene', label: '场景', icon: <MapPin size={14} /> },
  { value: 'image', label: '图片', icon: <ImageIcon size={14} /> },
  { value: 'video', label: '视频', icon: <Film size={14} /> },
  { value: 'audio', label: '音频', icon: <Music size={14} /> },
];

export function AssetPanel() {
  const showAssetPanel = useEditorStore((s) => s.showAssetPanel);
  const toggleAssetPanel = useEditorStore((s) => s.toggleAssetPanel);
  const canvas = useEditorStore((s) => s.canvas);
  const applyAssetToSelectedNode = useEditorStore((s) => s.applyAssetToSelectedNode);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [appliedAssetId, setAppliedAssetId] = useState<string | null>(null);
  // 跨项目复用：true 时显示所有项目的资产，false 时仅显示当前项目
  const [crossProject, setCrossProject] = useState(false);
  // 二次确认删除：记录正在确认删除的资产 ID
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (!showAssetPanel) return;
    let cancelled = false;
    setLoading(true);
    const canvasId = crossProject ? undefined : canvas?.id;
    api.listAssets(filter === 'all' ? undefined : filter, query || undefined, canvasId)
      .then((data) => {
        if (!cancelled) setAssets(data || []);
      })
      .catch(() => {
        if (!cancelled) setAssets([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [showAssetPanel, filter, query, canvas?.id, crossProject]);

  if (!showAssetPanel) return null;

  const selected = assets.find((a) => a.id === selectedId);

  const handleCopyPrompt = (prompt: string) => {
    navigator.clipboard.writeText(prompt).catch(() => {});
  };

  const handleDeleteAsset = async (assetId: string) => {
    setDeleting(true);
    try {
      await api.deleteAsset(assetId);
      setAssets((prev) => prev.filter((a) => a.id !== assetId));
      if (selectedId === assetId) setSelectedId(null);
      setConfirmDeleteId(null);
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败');
    } finally {
      setDeleting(false);
    }
  };

  const renderDeleteButton = (assetId: string) => {
    const isConfirming = confirmDeleteId === assetId;
    return (
      <button
        className={`flex items-center justify-center gap-1 py-1 text-[10px] rounded-lg transition-colors ${
          isConfirming
            ? 'bg-error/20 text-error border border-error/30 hover:bg-error/30'
            : 'bg-theme-input text-theme-sub border border-panel-border hover:text-error hover:border-error/30'
        }`}
        onClick={(e) => {
          e.stopPropagation();
          if (isConfirming) {
            handleDeleteAsset(assetId);
          } else {
            setConfirmDeleteId(assetId);
            // 3 秒后自动取消确认状态
            setTimeout(() => {
              setConfirmDeleteId((prev) => (prev === assetId ? null : prev));
            }, 3000);
          }
        }}
        disabled={deleting && isConfirming}
        title={isConfirming ? '再次点击确认删除' : '删除资产'}
      >
        {deleting && isConfirming ? (
          <><Check size={10} className="animate-pulse" /> 删除中...</>
        ) : isConfirming ? (
          <><Trash2 size={10} /> 确认删除？</>
        ) : (
          <><Trash2 size={10} /> 删除</>
        )}
      </button>
    );
  };

  const handleAssetDragStart = (e: React.DragEvent, asset: Asset) => {
    e.dataTransfer.setData('application/asset', JSON.stringify(asset));
    e.dataTransfer.effectAllowed = 'copy';
  };

  return (
    <div className="fixed right-4 top-20 bottom-6 w-80 glass rounded-2xl border border-panel-border shadow-soft-lg z-40 flex flex-col">
      <div className="h-12 border-b border-panel-border flex items-center justify-between px-4 shrink-0 bg-panel-bg">
        <h2 className="text-sm font-bold text-theme-main flex items-center gap-2">
          <Package size={16} className="text-accent" />
          资产库
        </h2>
        <div className="flex items-center gap-1">
          <button
            className={`flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] border transition-colors ${
              crossProject
                ? 'bg-accent/20 border-accent text-accent'
                : 'bg-transparent border-panel-border text-theme-sub hover:border-accent/30'
            }`}
            onClick={() => setCrossProject((v) => !v)}
            title={crossProject ? '当前显示所有项目资产' : '当前仅显示本项目资产，点击切换'}
          >
            <Globe size={11} />
            {crossProject ? '全部项目' : '本项目'}
          </button>
          <button className="btn-ghost p-1.5 rounded-xl" onClick={toggleAssetPanel} title="关闭">
            <X size={16} />
          </button>
        </div>
      </div>

      <div className="p-3 border-b border-panel-border space-y-2 shrink-0">
        <div className="relative">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-theme-hint" />
          <input
            className="input-field pl-8"
            placeholder="搜索资产..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="flex flex-wrap gap-1">
          {TYPE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setFilter(opt.value)}
              className={`flex items-center gap-1 px-2 py-1 rounded-md text-[10px] border transition-colors ${
                filter === opt.value
                  ? 'bg-accent/20 border-accent text-accent'
                  : 'bg-canvas-bg border-panel-border text-theme-sub hover:border-panel-border/80'
              }`}
            >
              {opt.icon}
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {loading ? (
          <div className="text-center text-theme-hint text-sm py-8">加载中...</div>
        ) : assets.length === 0 ? (
          <div className="text-center text-theme-hint text-sm py-8">
            <Package size={32} className="mx-auto mb-2 opacity-30" />
            暂无资产
          </div>
        ) : filter === 'character' ? (
          assets.map((asset) => {
            const meta = asset.meta || {};
            const features = (meta.immutable_features as string[]) || [];
            const charId = meta.char_id as string | undefined;
            const basePrompt = meta.base_prompt as string | undefined;
            return (
              <div
                key={asset.id}
                draggable
                onDragStart={(e) => handleAssetDragStart(e, asset)}
                onClick={() => setSelectedId(asset.id === selectedId ? null : asset.id)}
                className={`p-3 rounded-xl cursor-pointer transition-all shadow-soft ${
                  selectedId === asset.id
                    ? 'border-2 border-accent bg-accent/10'
                    : 'border border-panel-border bg-panel-bg hover:border-accent/30'
                }`}
              >
                <div className="flex gap-3">
                  <div className="w-24 h-32 rounded-lg bg-canvas-bg flex items-center justify-center shrink-0 overflow-hidden">
                    {asset.thumbnail_url || asset.file_url ? (
                      <img
                        src={asset.thumbnail_url || asset.file_url}
                        alt={asset.name}
                        className="w-full h-full object-cover"
                        onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                      />
                    ) : (
                      <User size={20} className="text-theme-hint" />
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-bold text-theme-main truncate">{asset.name}</div>
                    {charId && (
                      <div className="text-[10px] text-accent font-mono mt-0.5">ID: {charId}</div>
                    )}
                    {crossProject && asset.canvas_id && (
                      <div className="text-[9px] text-theme-hint mt-0.5" title="来自其他项目">
                        跨项目资产
                      </div>
                    )}
                    {features.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1.5">
                        {features.map((f, i) => (
                          <span key={i} className="text-[9px] px-1.5 py-0.5 rounded bg-accent/10 text-accent border border-accent/20">
                            {f}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
                {selectedId === asset.id && (
                  <div className="mt-2 pt-2 border-t border-panel-border/50 space-y-2">
                    {basePrompt && (
                      <div className="text-[10px] text-theme-hint font-mono bg-canvas-bg rounded p-1.5 line-clamp-4">
                        {basePrompt}
                      </div>
                    )}
                    <button
                      className={`w-full text-center py-1.5 text-[10px] rounded-lg flex items-center justify-center gap-1.5 transition-colors ${
                        appliedAssetId === asset.id
                          ? 'bg-green-500/20 text-green-400 border border-green-500/30'
                          : 'btn-primary'
                      }`}
                      onClick={(e) => {
                        e.stopPropagation();
                        applyAssetToSelectedNode({
                          id: asset.id,
                          file_url: asset.file_url,
                          asset_type: asset.asset_type,
                          meta: asset.meta,
                          name: asset.name,
                        });
                        setAppliedAssetId(asset.id);
                        setTimeout(() => setAppliedAssetId(null), 2000);
                      }}
                    >
                      {appliedAssetId === asset.id ? (
                        <><Check size={12} /> 已应用</>
                      ) : (
                        <><Link2 size={12} /> 应用到选中分镜</>
                      )}
                    </button>
                    <div className="flex gap-2">
                      <a
                        href={asset.file_url}
                        target="_blank"
                        rel="noreferrer"
                        className="flex-1 text-center btn-secondary py-1 text-[10px]"
                        onClick={(e) => e.stopPropagation()}
                      >
                        查看原文件
                      </a>
                      {renderDeleteButton(asset.id)}
                    </div>
                  </div>
                )}
              </div>
            );
          })
        ) : (
          assets.map((asset) => (
            <div
              key={asset.id}
              draggable
              onDragStart={(e) => handleAssetDragStart(e, asset)}
              onClick={() => setSelectedId(asset.id === selectedId ? null : asset.id)}
              className={`p-2.5 rounded-xl cursor-pointer transition-all shadow-soft ${
                selectedId === asset.id
                  ? 'border-2 border-accent bg-accent/10'
                  : 'border border-panel-border bg-panel-bg hover:border-accent/30 hover:-translate-y-0.5'
              }`}
            >
              <div className="flex items-center gap-2.5">
                <div className="w-12 h-12 rounded-lg bg-canvas-bg flex items-center justify-center shrink-0 overflow-hidden">
                  {asset.file_url?.match(/\.(jpg|jpeg|png|webp|gif|svg)(\?|$)/i) ? (
                    <img
                      src={asset.thumbnail_url || asset.file_url}
                      alt=""
                      className="w-full h-full object-cover"
                      onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                    />
                  ) : (
                    TYPE_OPTIONS.find((t) => t.value === asset.asset_type)?.icon || <Package size={16} />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-semibold text-theme-main truncate">{asset.name}</div>
                  <div className="text-[10px] text-theme-hint flex items-center gap-1">
                    <span className="px-1 rounded bg-canvas-bg">{asset.asset_type}</span>
                    <span className="truncate">{asset.id.slice(0, 8)}</span>
                    {crossProject && asset.canvas_id && (
                      <span className="text-accent shrink-0" title="来自其他项目">·跨项目</span>
                    )}
                  </div>
                </div>
              </div>

              {selectedId === asset.id && (
                <div className="mt-2 pt-2 border-t border-panel-border/50 space-y-2">
                  {asset.description && (
                    <div className="text-[10px] text-theme-sub line-clamp-3">{asset.description}</div>
                  )}
                  {asset.meta?.prompt && (
                    <div className="text-[10px] text-theme-hint font-mono bg-canvas-bg rounded p-1.5 line-clamp-4">
                      {asset.meta.prompt as string}
                    </div>
                  )}
                  <div className="flex gap-2">
                    <a
                      href={asset.file_url}
                      target="_blank"
                      rel="noreferrer"
                      className="flex-1 text-center btn-secondary py-1 text-[10px]"
                      onClick={(e) => e.stopPropagation()}
                    >
                      查看原文件
                    </a>
                    {asset.meta?.prompt && (
                      <button
                        className="flex-1 btn-secondary py-1 text-[10px]"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleCopyPrompt(asset.meta?.prompt as string);
                        }}
                      >
                        复制Prompt
                      </button>
                    )}
                    {renderDeleteButton(asset.id)}
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>

      <div className="p-3 border-t border-panel-border text-[10px] text-theme-hint shrink-0">
        共 {assets.length} 个资产{crossProject ? ' · 全部项目' : (canvas ? ` · 当前项目：${canvas.name}` : ' · 全部项目')}
      </div>
    </div>
  );
}
