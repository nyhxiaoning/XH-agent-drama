import { useState, useEffect, useRef, useLayoutEffect } from 'react';
import {
  X, Zap, GripVertical, Plus, AtSign,
  FileText, Image as ImageIcon, Music, Video, Check, Loader2, Maximize2,
  Send, Paperclip, Download, Coins, Globe,
  Sliders, Cpu, Ratio, Monitor, Clock, Volume2, Droplet, FlipHorizontal,
} from 'lucide-react';
import { useEditorStore } from '@/store/editor';
import { NODE_TYPE_CONFIG, STATUS_CONFIG } from '@/utils/constants';
import { api } from '@/utils/api';
import {
getModelsForNodeType,
getDefaultModelForNodeType,
ASPECT_RATIOS,
STYLE_PRESETS,
type StylePreset,
getVideoDurations,
getVideoResolutions,
getVideoAspectRatios,
supportsVideoSound,
supportsVideoWatermark,
supportsStartEndFrame,
IMAGE_RESOLUTIONS,
isSeedreamModel,
getEstimatedCost,
} from '@/utils/model-config';
import type { CanvasNode, NodeConfig, Asset } from '@/types';
import { ProviderIcon } from '@/components/ProviderIcon';
import { PresetMenu } from '@/components/PresetMenu';

interface NodePropertyPopupProps {
  node: CanvasNode;
  /** 节点左边缘屏幕 X 坐标 */
  screenX: number;
  /** 节点顶部屏幕 Y 坐标 */
  screenY: number;
  /** 节点在屏幕上的宽度（已乘 scale） */
  nodeWidth: number;
  /** 节点在屏幕上的高度（已乘 scale） */
  nodeHeight?: number;
  scale?: number;
  onClose: () => void;
  /** 是否自动打开资产选择器（快捷引用按钮触发） */
  autoOpenAssetPicker?: boolean;
}

export function NodePropertyPopup({ node, screenX, screenY, nodeWidth, nodeHeight = 160, scale = 1, onClose, autoOpenAssetPicker }: NodePropertyPopupProps) {
  const { updateNodeData, triggerGenerate, canvas } = useEditorStore();
  const modelPricing = useEditorStore((s) => s.modelPricing);
  const [editingPrompt, setEditingPrompt] = useState(node.prompt || '');
  const [editingStyle, setEditingStyle] = useState(node.style || '');
  const [editingTitle, setEditingTitle] = useState(node.title || '');
  const [context, setContext] = useState<string>('');
  const [contextLoading, setContextLoading] = useState(false);
  const popupRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const uploadMenuRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ x: screenX, y: screenY + nodeHeight + 12 });
  const draggingRef = useRef<{ startX: number; startY: number; px: number; py: number } | null>(null);
  // 用户拖拽标记：拖拽后不再自动跟随节点位置，直到切换节点
  const userDraggedRef = useRef(false);
  // 拖拽监听器引用，卸载时兜底清理
  const dragHandlersRef = useRef<{
    move: ((ev: MouseEvent) => void) | null;
    up: (() => void) | null;
  }>({ move: null, up: null });

  // 问题 7: 位置输入本地 state + 防抖
  const [posInput, setPosInput] = useState({ x: Math.round(node.x), y: Math.round(node.y) });
  const lastSavedPosRef = useRef({ x: Math.round(node.x), y: Math.round(node.y) });

  const [config, setConfig] = useState<NodeConfig>(() => {
    const defaultModel = getDefaultModelForNodeType(node.node_type);
    if (node.node_type === 'video') {
      return {
        model: defaultModel,
        aspect_ratio: getVideoAspectRatios(defaultModel)[0] || '16:9',
        duration: getVideoDurations(defaultModel)[0] || 5,
        resolution: getVideoResolutions(defaultModel)[0] || '1080P',
        // 支持声音的模型默认开启，避免用户忘记开导致生成的视频无声浪费算力
        sound: supportsVideoSound(defaultModel),
        watermark: false,
        start_end_frame: false,
        ...(node.config as NodeConfig | undefined),
      };
    }
    return {
      model: defaultModel,
      aspect_ratio: '1:1',
      ...(node.config as NodeConfig | undefined),
    };
  });
  const estimatedCost = getEstimatedCost({ ...node, config: config as Record<string, unknown> }, modelPricing);

  const [showUploadMenu, setShowUploadMenu] = useState(false);
  const [showStylePicker, setShowStylePicker] = useState(false);
  const [showModelPicker, setShowModelPicker] = useState(false);
  const [showParamsPicker, setShowParamsPicker] = useState(false);
  const [showAssetPicker, setShowAssetPicker] = useState(false);
  const [lightbox, setLightbox] = useState<{ url: string; type: 'image' | 'video' } | null>(null);
  const stylePickerRef = useRef<HTMLDivElement>(null);
  const modelPickerRef = useRef<HTMLDivElement>(null);
  const paramsPickerRef = useRef<HTMLDivElement>(null);

  const downloadLightbox = async (url: string, type: 'image' | 'video') => {
    try {
      const response = await fetch(url, { mode: 'cors' });
      const blob = await response.blob();
      const blobUrl = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      const ext = type === 'image' ? 'jpg' : 'mp4';
      const filename = url.split('/').pop()?.split('?')[0] || `download.${ext}`;
      a.download = filename.endsWith(`.${ext}`) ? filename : `${filename}.${ext}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(blobUrl);
    } catch (err) {
      // 降级：直接打开新标签页
      window.open(url, '_blank');
    }
  };

  const [expandedPrompt, setExpandedPrompt] = useState(false);
  const [expandedPromptValue, setExpandedPromptValue] = useState(node.prompt || '');
  const [uploading, setUploading] = useState(false);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [assetsLoading, setAssetsLoading] = useState(false);

  const cfg = NODE_TYPE_CONFIG[node.node_type as keyof typeof NODE_TYPE_CONFIG] || { label: '节点', icon: '📦', color: '#6b7280', desc: '' };
  const statusCfg = STATUS_CONFIG[node.status as keyof typeof STATUS_CONFIG] || { label: node.status || '未知', color: '#6b7280', bgClass: 'bg-node-pending' };
  const models = getModelsForNodeType(node.node_type);

  // 问题 6: effect 依赖只保留 node.id，避免 WS 更新覆盖未保存输入
  useEffect(() => {
    setEditingPrompt(node.prompt || '');
    setExpandedPromptValue(node.prompt || '');
    setEditingStyle(node.style || '');
    setEditingTitle(node.title || '');
    const dm = getDefaultModelForNodeType(node.node_type);
    if (node.node_type === 'video') {
      setConfig({
        model: dm,
        aspect_ratio: getVideoAspectRatios(dm)[0] || '16:9',
        duration: getVideoDurations(dm)[0] || 5,
        resolution: getVideoResolutions(dm)[0] || '1080P',
        // 支持声音的模型默认开启，避免用户忘记开导致生成的视频无声浪费算力
        sound: supportsVideoSound(dm),
        watermark: false,
        start_end_frame: false,
        ...(node.config as NodeConfig | undefined),
      });
    } else {
      setConfig({
        model: dm,
        aspect_ratio: '1:1',
        ...(node.config as NodeConfig | undefined),
      });
    }
    setContext('');
    setContextLoading(false);

    if (node.node_type === 'storyboard' || node.node_type === 'image') {
      setContextLoading(true);
      api.getNodeContext(node.id)
        .then((ctx: unknown) => {
          const c = ctx as { connected_nodes?: { title: string; node_type: string }[]; node?: { prompt?: string } };
          if (c?.connected_nodes?.length) {
            const parts = c.connected_nodes.map((n) => `[${n.node_type}] ${n.title}`);
            setContext(parts.join('\n'));
          } else if (c?.node?.prompt) {
            setContext(c.node.prompt);
          }
        })
        .catch(() => {})
        .finally(() => setContextLoading(false));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [node.id]);

  // 问题 1: 弹窗挂载时主动拉取已引用资产，确保已引用资产在弹窗打开时就显示
  useEffect(() => {
    const refIds = (node.config as NodeConfig | undefined)?.reference_asset_ids || [];
    if (!refIds.length) return;
    let cancelled = false;
    api.listAssets(undefined, undefined, canvas?.id)
      .then((list) => {
        if (cancelled) return;
        setAssets((prev) => {
          const seen = new Set(prev.map((a) => a.id));
          const merged = [...prev];
          for (const a of list) {
            if (!seen.has(a.id)) {
              merged.push(a);
              seen.add(a.id);
            }
          }
          return merged;
        });
      })
      .catch(() => {});
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [node.id]);

  // 弹窗固定在节点卡片下方，左对齐
  // 用户拖拽后不再自动跟随，直到切换节点
  useLayoutEffect(() => {
    if (userDraggedRef.current) return;
    const el = popupRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const gap = 8;
    // 固定放节点下方，左对齐
    let x = screenX;
    let y = screenY + nodeHeight + gap;
    // 水平边界检测：超出右侧则右对齐到视口
    if (x + rect.width > vw - 8) {
      x = Math.max(8, vw - rect.width - 8);
    }
    if (x < 8) x = 8;
    // 垂直边界：下方放不下时向上贴齐，但不翻到节点上方
    if (y + rect.height > vh - 8) {
      y = Math.max(8, vh - rect.height - 8);
    }
    setPosition({ x, y });
  }, [screenX, screenY, nodeWidth, nodeHeight, scale]);

  // 切换节点时重置拖拽标记，让面板重新出现在新节点右侧
  useEffect(() => {
    userDraggedRef.current = false;
  }, [node.id]);

  // 卸载时兜底清理拖拽监听器
  useEffect(() => {
    return () => {
      if (dragHandlersRef.current.move) {
        window.removeEventListener('mousemove', dragHandlersRef.current.move);
      }
      if (dragHandlersRef.current.up) {
        window.removeEventListener('mouseup', dragHandlersRef.current.up);
      }
    };
  }, []);

  // 问题 5: upload 菜单外部点击关闭
  useEffect(() => {
    if (!showUploadMenu) return;
    const handler = (e: MouseEvent) => {
      if (uploadMenuRef.current && !uploadMenuRef.current.contains(e.target as Node)) {
        setShowUploadMenu(false);
      }
    };
    document.addEventListener('click', handler);
    return () => document.removeEventListener('click', handler);
  }, [showUploadMenu]);

  // 风格选择器外部点击关闭
  useEffect(() => {
    if (!showStylePicker) return;
    const handler = (e: MouseEvent) => {
      if (stylePickerRef.current && !stylePickerRef.current.contains(e.target as Node)) {
        setShowStylePicker(false);
      }
    };
    document.addEventListener('click', handler);
    return () => document.removeEventListener('click', handler);
  }, [showStylePicker]);

  // 模型选择器外部点击关闭
  useEffect(() => {
    if (!showModelPicker) return;
    const handler = (e: MouseEvent) => {
      if (modelPickerRef.current && !modelPickerRef.current.contains(e.target as Node)) {
        setShowModelPicker(false);
      }
    };
    document.addEventListener('click', handler);
    return () => document.removeEventListener('click', handler);
  }, [showModelPicker]);

  // 参数选择器外部点击关闭
  useEffect(() => {
    if (!showParamsPicker) return;
    const handler = (e: MouseEvent) => {
      if (paramsPickerRef.current && !paramsPickerRef.current.contains(e.target as Node)) {
        setShowParamsPicker(false);
      }
    };
    document.addEventListener('click', handler);
    return () => document.removeEventListener('click', handler);
  }, [showParamsPicker]);

  // 问题 9: Escape 键关闭
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  // 问题 7: 节点切换时同步位置输入与已保存值
  useEffect(() => {
    setPosInput({ x: Math.round(node.x), y: Math.round(node.y) });
    lastSavedPosRef.current = { x: Math.round(node.x), y: Math.round(node.y) };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [node.id]);

  // 快捷引用：自动打开资产选择器
  useEffect(() => {
    if (autoOpenAssetPicker) {
      openAssetPicker();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoOpenAssetPicker, node.id]);

  // 问题 7: 位置输入 300ms 防抖后才调 api
  useEffect(() => {
    const t = setTimeout(() => {
      if (posInput.x !== lastSavedPosRef.current.x || posInput.y !== lastSavedPosRef.current.y) {
        updateNodeData(node.id, { x: posInput.x, y: posInput.y });
        lastSavedPosRef.current = { ...posInput };
      }
    }, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [posInput.x, posInput.y]);

  // 问题 10: saveNode 中 config 类型断言统一一次
  const saveNode = (updates: Partial<CanvasNode> & { config?: NodeConfig }) => {
    const { config: cfgUpdates, ...rest } = updates;
    const payload: Partial<CanvasNode> = { ...rest };
    if (cfgUpdates) {
      payload.config = cfgUpdates as Record<string, unknown>;
    }
    updateNodeData(node.id, payload);
  };

  const savePrompt = () => {
    const updates: Partial<CanvasNode> & { config?: NodeConfig } = {};
    if (editingPrompt !== (node.prompt || '')) updates.prompt = editingPrompt;
    if (editingStyle !== (node.style || '')) updates.style = editingStyle;
    if (editingTitle !== (node.title || '')) updates.title = editingTitle;
    if (Object.keys(updates).length) saveNode(updates);
  };

  const openExpandedPrompt = () => {
    setExpandedPromptValue(editingPrompt);
    setExpandedPrompt(true);
  };

  const confirmExpandedPrompt = () => {
    setEditingPrompt(expandedPromptValue);
    if (expandedPromptValue !== (node.prompt || '')) {
      updateNodeData(node.id, { prompt: expandedPromptValue });
    }
    setExpandedPrompt(false);
  };

  const updateConfig = (patch: Partial<NodeConfig>) => {
    const next = { ...config, ...patch };
    setConfig(next);
    saveNode({ config: next });
  };

  // 视频节点切换模型时，重置不兼容的 duration / resolution / aspect_ratio
  const handleModelChange = (newModel: string) => {
    if (node.node_type !== 'video') {
      updateConfig({ model: newModel });
      return;
    }
    const patch: Partial<NodeConfig> = { model: newModel };
    const durations = getVideoDurations(newModel);
    if (!durations.includes(config.duration || 5)) {
      patch.duration = durations[0];
    }
    const resolutions = getVideoResolutions(newModel);
    if (!resolutions.includes(config.resolution || '')) {
      patch.resolution = resolutions[0];
    }
    const ratios = getVideoAspectRatios(newModel);
    if (ratios.length > 0 && !ratios.includes(config.aspect_ratio || '')) {
      patch.aspect_ratio = ratios[0];
    }
    if (supportsVideoSound(newModel)) {
      // 切到支持声音的模型时，若用户未显式开启则默认开启，避免忘开导致无声浪费算力
      if (!config.sound) patch.sound = true;
    } else {
      patch.sound = false;
    }
    if (!supportsVideoWatermark(newModel)) {
      patch.watermark = false;
    }
    if (!supportsStartEndFrame(newModel)) {
      patch.start_end_frame = false;
    }
    updateConfig(patch);
  };

  const handleHeaderMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    userDraggedRef.current = true;
    draggingRef.current = { startX: e.clientX, startY: e.clientY, px: position.x, py: position.y };
    const handleMove = (ev: MouseEvent) => {
      if (!draggingRef.current) return;
      const dx = ev.clientX - draggingRef.current.startX;
      const dy = ev.clientY - draggingRef.current.startY;
      setPosition({ x: draggingRef.current.px + dx, y: draggingRef.current.py + dy });
    };
    const handleUp = () => {
      draggingRef.current = null;
      window.removeEventListener('mousemove', handleMove);
      window.removeEventListener('mouseup', handleUp);
      dragHandlersRef.current.move = null;
      dragHandlersRef.current.up = null;
    };
    dragHandlersRef.current.move = handleMove;
    dragHandlersRef.current.up = handleUp;
    window.addEventListener('mousemove', handleMove);
    window.addEventListener('mouseup', handleUp);
  };

  const handleRegenerate = () => {
    // 生成前先保存未提交的 prompt/style/title，避免使用旧值
    savePrompt();
    // 传入本地 config，避免 store 中的 config 被 WS 推送覆盖后使用旧值
    triggerGenerate(node.id, 1, config as Record<string, unknown>);
  };

  const handleUploadClick = (type: 'text' | 'image' | 'audio' | 'video') => {
    setShowUploadMenu(false);
    if (!fileInputRef.current) return;
    fileInputRef.current.accept = {
      text: '.txt,.md,.json',
      image: 'image/*',
      audio: 'audio/*',
      video: 'video/*',
    }[type];
    fileInputRef.current.dataset.type = type;
    fileInputRef.current.click();
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const type = (e.target.dataset.type as 'text' | 'image' | 'audio' | 'video') || 'other';
    const assetTypeMap: Record<string, string> = {
      text: 'other',
      image: 'image',
      audio: 'audio',
      video: 'video',
    };
    setUploading(true);
    try {
      const asset = await api.uploadAsset(file, {
        name: file.name,
        assetType: assetTypeMap[type] || 'other',
        description: `节点 ${node.title} 上传的${type}素材`,
        canvasId: canvas?.id,
      });
      // 将新上传的资产加入 assets 状态，使其立即显示在已引用资产区域
      setAssets((prev) => {
        if (prev.some((a) => a.id === asset.id)) return prev;
        return [...prev, asset];
      });
      attachAsset(asset);
    } catch (err) {
      alert(err instanceof Error ? err.message : '上传失败');
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  };

  const [crossProject, setCrossProject] = useState(false);

  const openAssetPicker = async () => {
    setShowAssetPicker(true);
    setAssetsLoading(true);
    try {
      const relevantTypes: Record<string, string[]> = {
        image: ['image', 'character', 'scene'],
        storyboard: ['image', 'character', 'scene'],
        video: ['image', 'video', 'audio', 'character', 'scene'],
        audio: ['audio'],
      };
      const types = relevantTypes[node.node_type] || [];
      const canvasId = crossProject ? undefined : canvas?.id;
      let all: Asset[] = [];
      if (types.length) {
        const results = await Promise.all(
          types.map((t) => api.listAssets(t, undefined, canvasId).catch(() => [] as Asset[]))
        );
        all = results.flat();
      } else {
        all = await api.listAssets(undefined, undefined, canvasId).catch(() => [] as Asset[]);
      }
      const seen = new Set<string>();
      setAssets(all.filter((a) => { if (seen.has(a.id)) return false; seen.add(a.id); return true; }));
    } finally {
      setAssetsLoading(false);
    }
  };

  const attachAsset = (asset: Asset) => {
    const refs = new Set(config.reference_asset_ids || []);
    refs.add(asset.id);
    const fileRefs = new Set(config.reference_images || []);
    if (asset.asset_type === 'image' || asset.asset_type === 'character' || asset.asset_type === 'scene') {
      fileRefs.add(asset.file_url);
    }
    const next: Partial<NodeConfig> = { reference_asset_ids: Array.from(refs) };
    if (fileRefs.size) next.reference_images = Array.from(fileRefs);
    if (asset.asset_type === 'audio') next.reference_audio = asset.file_url;
    if (asset.asset_type === 'video') next.reference_video = asset.file_url;
    updateConfig(next);
  };

  const detachAsset = (assetId: string) => {
    const asset = assets.find((a) => a.id === assetId);
    const next: NodeConfig = { ...config };
    next.reference_asset_ids = (next.reference_asset_ids || []).filter((id) => id !== assetId);
    if (asset && asset.file_url) {
      next.reference_images = (next.reference_images || []).filter((u) => u !== asset.file_url);
      if (next.reference_audio === asset.file_url) next.reference_audio = undefined;
      if (next.reference_video === asset.file_url) next.reference_video = undefined;
    }
    updateConfig(next);
  };

  const referencedAssets = assets.filter((a) => (config.reference_asset_ids || []).includes(a.id));

  const hasMediaOptions =
    node.node_type === 'image' ||
    node.node_type === 'video' ||
    node.node_type === 'storyboard' ||
    node.node_type === 'character' ||
    node.node_type === 'scene' ||
    node.node_type === 'audio' ||
    node.node_type === 'script';
  const hasModel = models.length > 0;

  // 组合参数摘要：比例 + 分辨率 + 时长 + 声音/水印
  const showParamsButton =
    node.node_type === 'image' || node.node_type === 'video' ||
    node.node_type === 'storyboard' || node.node_type === 'character' ||
    node.node_type === 'scene';
  const paramsSummary = [
    config.aspect_ratio,
    config.resolution,
    node.node_type === 'video' ? `${config.duration || 5}s` : '',
  ].filter(Boolean).join(' · ');
  const activeParamCount = [
    config.aspect_ratio, config.resolution,
    node.node_type === 'video' ? config.duration : null,
    node.node_type === 'video' && config.sound ? 'sound' : null,
    node.node_type === 'video' && config.watermark ? 'watermark' : null,
    node.node_type === 'video' && config.start_end_frame ? 'start_end' : null,
  ].filter(Boolean).length;

  // 点击外部关闭弹窗（不阻挡节点卡片的点击）
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      // 点击弹窗内部不关闭
      if (popupRef.current?.contains(e.target as Node)) return;
      // 点击节点卡片不关闭（让卡片自己处理选中）
      if ((e.target as HTMLElement).closest('.node-card')) return;
      // 点击其他 UI（如工具栏、弹窗内选择器）不关闭
      if ((e.target as HTMLElement).closest('.no-pan')) return;
      onClose();
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [onClose]);

  return (
    <>
      <div
        ref={popupRef}
        className="fixed z-[100] w-[760px] max-h-[80vh] rounded-3xl shadow-soft-lg flex flex-col no-pan panel-solid border border-panel-border"
        style={{ left: position.x, top: position.y }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* 标题栏：可拖拽 */}
        <div
          className="h-11 flex items-center justify-between px-4 shrink-0 cursor-move rounded-t-3xl"
          onMouseDown={handleHeaderMouseDown}
        >
          <div className="flex items-center gap-2.5">
            <GripVertical size={14} className="text-theme-sub" />
            <span className="text-lg">{cfg.icon}</span>
            <input
              className="bg-transparent text-sm font-semibold text-theme-main focus:outline-none border-b border-transparent focus:border-accent py-0.5 max-w-[160px]"
              value={editingTitle}
              onChange={(e) => setEditingTitle(e.target.value)}
              onBlur={savePrompt}
              onMouseDown={(e) => e.stopPropagation()}
            />
          </div>
          <div className="flex items-center gap-0.5">
            <button
              className={`p-1.5 rounded-full transition-colors ${
                node.status === 'processing'
                  ? 'text-theme-hint cursor-not-allowed'
                  : 'hover:bg-panel-hover text-theme-muted'
              }`}
              onClick={node.status === 'processing' ? undefined : handleRegenerate}
              disabled={node.status === 'processing'}
              title={node.status === 'success' ? '重新生成' : '生成'}
            >
              {node.status === 'processing' ? <Loader2 size={15} className="animate-spin" /> : <Zap size={15} />}
            </button>
            <button className="p-1.5 rounded-full hover:bg-panel-hover text-theme-sub transition-colors" onClick={onClose} title="关闭">
              <X size={15} />
            </button>
          </div>
        </div>

        {/* 内容区：简洁输入 */}
        <div className="flex-1 overflow-y-auto overflow-x-hidden px-4 pb-2 rounded-t-3xl">
          {/* 状态 + 模型 */}
          <div className="flex items-center gap-2 text-[11px] text-theme-sub mb-2">
            <span className={`status-dot ${statusCfg.bgClass}`} />
            <span style={{ color: statusCfg.color }}>{statusCfg.label}</span>
            {config.model && (
              <span className="ml-auto flex items-center gap-1.5">
                <ProviderIcon provider={getModelsForNodeType(node.node_type).find(m => m.id === config.model)?.provider || ''} modelId={config.model} size={12} className="text-accent" />
                {getModelsForNodeType(node.node_type).find(m => m.id === config.model)?.label || config.model}
              </span>
            )}
          </div>

          {/* 分镜元数据 */}
          {node.node_type === 'storyboard' && (
            <div className="flex flex-wrap gap-1 text-[10px] mb-2">
              {(node.config as Record<string, unknown> | undefined)?.storyboard_id && (
                <span className="px-1.5 py-0.5 rounded-md bg-theme-input text-theme-muted border border-panel-border">
                  {(node.config as Record<string, unknown>).storyboard_id as string}
                </span>
              )}
              {(node.config as Record<string, unknown> | undefined)?.prev_storyboard_id && (
                <span className="px-1.5 py-0.5 rounded-md bg-accent/10 text-accent border border-accent/30" title="上一镜">
                  ← {(node.config as Record<string, unknown>).prev_storyboard_id as string}
                </span>
              )}
              {(node.config as Record<string, unknown> | undefined)?.shot_type && (
                <span className="px-1.5 py-0.5 rounded-md bg-theme-input text-theme-muted border border-panel-border">
                  {(node.config as Record<string, unknown>).shot_type as string}
                </span>
              )}
              {(node.config as Record<string, unknown> | undefined)?.camera_movement && (
                <span className="px-1.5 py-0.5 rounded-md bg-theme-input text-theme-muted border border-panel-border">
                  {(node.config as Record<string, unknown>).camera_movement as string}
                </span>
              )}
              {(node.config as Record<string, unknown> | undefined)?.duration_seconds && (
                <span className="px-1.5 py-0.5 rounded-md bg-theme-input text-theme-muted border border-panel-border">
                  {(node.config as Record<string, unknown>).duration_seconds as number}s
                </span>
              )}
            </div>
          )}

          {/* 主 Prompt 输入区：无边框、透明，带放大按钮 */}
          <div className="relative">
            <textarea
              className="w-full bg-transparent text-[14px] text-theme-main placeholder:text-theme-hint focus:outline-none resize-none leading-relaxed pr-7"
              value={editingPrompt}
              onChange={(e) => setEditingPrompt(e.target.value)}
              onBlur={savePrompt}
              placeholder="输入描述词..."
              rows={3}
            />
            <button
              className="absolute top-0 right-0 p-1 rounded-md hover:bg-panel-hover text-theme-sub hover:text-theme-muted transition-colors"
              onClick={openExpandedPrompt}
              title="放大编辑提示词"
            >
              <Maximize2 size={14} />
            </button>
          </div>

          {/* 风格输入 */}
          {(node.node_type === 'image' || node.node_type === 'video' || node.node_type === 'storyboard' || node.node_type === 'character' || node.node_type === 'scene') && (
            <input
              className="w-full mt-2 bg-transparent text-[12px] text-theme-muted placeholder:text-theme-hint focus:outline-none"
              value={editingStyle}
              onChange={(e) => setEditingStyle(e.target.value)}
              onBlur={savePrompt}
              placeholder="风格：例如电影质感、日系二次元..."
            />
          )}

          {/* 已引用资产 */}
          {referencedAssets.length > 0 && (
            <div className="flex flex-wrap gap-2 mt-3">
              {referencedAssets.map((asset) => {
                const isImage = asset.asset_type === 'image' || asset.asset_type === 'character' || asset.asset_type === 'scene';
                const isVideo = asset.asset_type === 'video';
                const isAudio = asset.asset_type === 'audio';
                return (
                  <div
                    key={asset.id}
                    className="relative group rounded-xl overflow-hidden border border-accent/30 bg-accent/5"
                  >
                    <div className="w-16 h-16 flex items-center justify-center overflow-hidden">
                      {isImage ? (
                        <img src={asset.thumbnail_url || asset.file_url} alt={asset.name} className="w-full h-full object-cover" />
                      ) : isVideo ? (
                        <video src={asset.file_url} className="w-full h-full object-cover" preload="metadata" muted />
                      ) : isAudio ? (
                        <div className="flex flex-col items-center justify-center w-full h-full text-theme-muted">
                          <Music size={18} />
                          <span className="text-[8px] mt-0.5">音频</span>
                        </div>
                      ) : (
                        <div className="flex flex-col items-center justify-center w-full h-full text-theme-muted">
                          <FileText size={18} />
                          <span className="text-[8px] mt-0.5">文件</span>
                        </div>
                      )}
                    </div>
                    <button
                      className="absolute top-0.5 right-0.5 w-4 h-4 rounded-full bg-black/60 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity hover:bg-error"
                      onClick={() => detachAsset(asset.id)}
                      title="移除"
                    >
                      <X size={10} />
                    </button>
                    <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/70 to-transparent px-1 py-0.5">
                      <span className="text-[8px] text-white truncate block">{asset.name}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* 上游上下文 */}
          {context && (
            <div className="mt-3">
              <div className="bg-theme-input rounded-xl p-2.5 text-[10px] text-theme-muted leading-relaxed max-h-28 overflow-y-auto font-mono border border-panel-border">
                {contextLoading ? '加载中...' : context}
              </div>
            </div>
          )}

          {/* 进度 */}
          {node.status === 'processing' && (
            <div className="mt-3">
              <div className="h-1.5 bg-panel-border rounded-full overflow-hidden">
                <div className="h-full bg-accent rounded-full transition-all duration-300" style={{ width: `${node.progress}%` }} />
              </div>
              <div className="text-[10px] text-accent mt-1">{Math.round(node.progress)}%</div>
            </div>
          )}

          {/* 结果预览 */}
          {node.result_url && node.status === 'success' && (
            <div className="mt-3">
              <div
                className="relative bg-panel-hover rounded-xl overflow-hidden cursor-pointer group h-24"
                onClick={() => {
                  const isVideo = node.node_type === 'video';
                  setLightbox({ url: node.result_url!, type: isVideo ? 'video' : 'image' });
                }}
              >
                {(node.node_type === 'image' || node.node_type === 'storyboard' || node.node_type === 'character' || node.node_type === 'scene') ? (
                  <img src={node.thumbnail_url || node.result_url} alt="" className="w-full h-full object-cover rounded-xl" />
                ) : node.node_type === 'video' ? (
                  <video src={node.result_url} className="w-full h-full object-cover rounded-xl" preload="metadata" muted />
                ) : (
                  <a href={node.result_url} target="_blank" rel="noreferrer" className="text-accent text-xs p-2 block truncate hover:underline" onClick={(e) => e.stopPropagation()}>
                    查看结果 →
                  </a>
                )}
                <div className="absolute inset-0 flex items-center justify-center bg-black/0 group-hover:bg-black/30 transition-colors">
                  <Maximize2 size={18} className="text-white opacity-0 group-hover:opacity-100 transition-opacity" />
                </div>
              </div>
              {/* 局部重绘已移至节点上方浮动菜单栏（NodeActionBar） */}
            </div>
          )}

          {/* 位置输入 */}
          <div className="mt-3 flex gap-2">
            <input
              type="number"
              className="w-20 bg-theme-input rounded-lg px-2 py-1 text-[11px] text-theme-main focus:outline-none border border-transparent focus:border-accent"
              value={posInput.x}
              onChange={(e) => setPosInput((p) => ({ ...p, x: Number(e.target.value) }))}
              title="X 坐标"
            />
            <input
              type="number"
              className="w-20 bg-theme-input rounded-lg px-2 py-1 text-[11px] text-theme-main focus:outline-none border border-transparent focus:border-accent"
              value={posInput.y}
              onChange={(e) => setPosInput((p) => ({ ...p, y: Number(e.target.value) }))}
              title="Y 坐标"
            />
          </div>
        </div>

        {/* 底部工具栏：单排，全部控件一行排列 */}
        {hasMediaOptions && (
          <div className="px-4 py-2.5 border-t border-panel-border rounded-b-3xl">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-0 bg-theme-input rounded-full h-9">
                {/* 上传 */}
                <div className="relative" ref={uploadMenuRef}>
                  <button
                    className="w-9 h-9 rounded-l-full bg-transparent hover:bg-panel-hover text-theme-muted flex items-center justify-center transition-colors"
                    onClick={() => setShowUploadMenu((v) => !v)}
                    title="上传"
                  >
                    <Paperclip size={16} />
                  </button>
                  {showUploadMenu && (
                    <div className="absolute left-0 bottom-full mb-2 w-32 rounded-2xl border border-panel-border shadow-soft-lg z-50 py-1.5 overflow-hidden panel-solid">
                      {[
                        { key: 'text', icon: FileText, label: '文本' },
                        { key: 'image', icon: ImageIcon, label: '图片' },
                        { key: 'audio', icon: Music, label: '音频' },
                        { key: 'video', icon: Video, label: '视频' },
                      ].map((item) => (
                        <button
                          key={item.key}
                          className="w-full flex items-center gap-2 px-3 py-2 text-[11px] text-theme-muted hover:bg-panel-hover"
                          onClick={() => handleUploadClick(item.key as 'text' | 'image' | 'audio' | 'video')}
                        >
                          <item.icon size={13} />
                          {item.label}
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                <div className="w-px h-5 bg-panel-border shrink-0" />

                {/* 引用 */}
                <button
                  className="w-9 h-9 bg-transparent hover:bg-panel-hover text-theme-muted flex items-center justify-center transition-colors"
                  onClick={openAssetPicker}
                  title="引用"
                >
                  <AtSign size={16} />
                </button>

                <div className="w-px h-5 bg-panel-border shrink-0" />

                {/* 模型 — 卡片选择 */}
                {hasModel && (
                  <div className="relative" ref={modelPickerRef}>
                    <button
                      className="h-9 min-w-[100px] px-3 bg-transparent text-[11px] text-theme-main flex items-center gap-1.5 transition-all duration-150 hover:bg-panel-hover focus:outline-none cursor-pointer"
                      onClick={() => { setShowModelPicker((v) => !v); setShowParamsPicker(false); setShowStylePicker(false); }}
                      title="模型"
                    >
                      <Cpu size={13} className="text-accent shrink-0" />
                      <span className="truncate max-w-[80px]">{models.find(m => m.id === config.model)?.label || '模型'}</span>
                    </button>
                    {showModelPicker && (
                      <div className="absolute left-0 bottom-full mb-2 w-[340px] max-h-[300px] overflow-y-auto rounded-2xl border border-panel-border shadow-soft-lg z-50 p-2.5 panel-solid animate-slide-down">
                        <div className="text-[10px] text-theme-hint font-semibold uppercase tracking-wider mb-2 flex items-center gap-1.5">
                          <Cpu size={11} className="text-accent" />
                          选择模型
                        </div>
                        <div className="grid grid-cols-2 gap-1.5">
                          {models.map((m) => {
                            const selected = config.model === m.id;
                            return (
                              <button
                                key={m.id}
                                onClick={() => {
                                  handleModelChange(m.id);
                                  setShowModelPicker(false);
                                }}
                                className={`flex flex-col items-start gap-1 p-2.5 rounded-xl border text-left transition-all duration-150 ${
                                  selected
                                    ? 'border-accent bg-accent/10 ring-1 ring-accent/30'
                                    : 'border-panel-border bg-theme-input hover:border-accent/40 hover:bg-panel-hover'
                                }`}
                                title={`${m.label} (${m.provider})`}
                              >
                                <div className="flex items-center gap-1.5 w-full">
                                  <ProviderIcon provider={m.provider} modelId={m.id} size={14} className={selected ? 'text-accent' : 'text-theme-sub'} />
                                  <span className={`text-[11px] font-medium truncate flex-1 ${selected ? 'text-accent' : 'text-theme-main'}`}>{m.label}</span>
                                  {selected && <Check size={12} className="text-accent shrink-0" />}
                                </div>
                                <span className="text-[9px] text-theme-sub uppercase tracking-wider">{m.provider}</span>
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* 风格 */}
                {(node.node_type === 'image' || node.node_type === 'video' || node.node_type === 'storyboard' || node.node_type === 'character' || node.node_type === 'scene') && (
                  <>
                    <div className="w-px h-5 bg-panel-border shrink-0" />
                    <div className="relative" ref={stylePickerRef}>
                      <button
                        className="h-9 min-w-[80px] px-3 bg-transparent text-[11px] text-theme-main flex items-center gap-1.5 transition-all duration-150 hover:bg-panel-hover focus:outline-none focus:text-accent cursor-pointer"
                        onClick={() => setShowStylePicker((v) => !v)}
                        title="风格"
                      >
                        <span className="truncate max-w-[80px]">{editingStyle || '风格'}</span>
                      </button>
                      {showStylePicker && (
                        <div className="absolute left-0 bottom-full mb-2 w-[280px] sm:w-[320px] md:w-[380px] max-h-[320px] overflow-y-auto rounded-2xl border border-panel-border shadow-soft-lg z-50 p-3 panel-solid animate-slide-down">
                          <div className="text-[10px] text-theme-hint font-semibold uppercase tracking-wider mb-2">选择视觉风格</div>
                          <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2">
                            {STYLE_PRESETS.map((s) => {
                              const selected = editingStyle === s.name;
                              return (
                                <button
                                  key={s.name}
                                  onClick={() => {
                                    setEditingStyle(s.name);
                                    updateNodeData(node.id, { style: s.name });
                                    setShowStylePicker(false);
                                  }}
                                  className={`group relative overflow-hidden rounded-xl border text-left transition-all ${
                                    selected
                                      ? 'border-accent ring-1 ring-accent shadow-glow'
                                      : 'border-panel-border hover:border-accent'
                                  }`}
                                  title={s.name}
                                >
                                  <div className="aspect-[4/3] w-full overflow-hidden">
                                    <img
                                      src={s.image}
                                      alt={s.name}
                                      className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-110"
                                      onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                                    />
                                    <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/20 to-transparent" />
                                  </div>
                                  <div className="absolute bottom-0 left-0 right-0 p-1.5">
                                    <span className="text-[10px] font-medium text-white drop-shadow-md line-clamp-1">
                                      {s.name}
                                    </span>
                                  </div>
                                  {selected && (
                                    <div className="absolute top-1 right-1 w-4 h-4 rounded-full bg-accent text-white flex items-center justify-center">
                                      <Check size={10} />
                                    </div>
                                  )}
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      )}
                    </div>
                  </>
                )}

                {/* 组合参数 — 比例/分辨率/时长/声音/水印 */}
                {showParamsButton && (
                  <>
                    <div className="w-px h-5 bg-panel-border shrink-0" />
                    <div className="relative" ref={paramsPickerRef}>
                      <button
                        className="h-9 min-w-[80px] px-3 bg-transparent text-[11px] text-theme-main flex items-center gap-1.5 transition-all duration-150 hover:bg-panel-hover focus:outline-none focus:text-accent cursor-pointer"
                        onClick={() => { setShowParamsPicker((v) => !v); setShowModelPicker(false); setShowStylePicker(false); }}
                        title="参数设置"
                      >
                        <Sliders size={13} className="text-theme-sub shrink-0" />
                        <span className="truncate max-w-[100px]">{paramsSummary || '参数'}</span>
                        {activeParamCount > 0 && (
                          <span className="ml-0.5 w-4 h-4 rounded-full bg-accent/20 text-accent text-[8px] flex items-center justify-center shrink-0">{activeParamCount}</span>
                        )}
                      </button>
                      {showParamsPicker && (
                        <div className="absolute left-0 bottom-full mb-2 w-[360px] max-h-[360px] overflow-y-auto rounded-2xl border border-panel-border shadow-soft-lg z-50 p-3 panel-solid animate-slide-down">
                          <div className="text-[10px] text-theme-hint font-semibold uppercase tracking-wider mb-2.5 flex items-center gap-1.5">
                            <Sliders size={11} className="text-accent" />
                            参数设置
                          </div>

                          {/* 比例 */}
                          {(node.node_type === 'image' || node.node_type === 'video' || node.node_type === 'storyboard' || node.node_type === 'character' || node.node_type === 'scene') && (
                            <div className="mb-3">
                              <div className="text-[10px] text-theme-sub font-medium mb-1.5 flex items-center gap-1">
                                <Ratio size={10} /> 画面比例
                              </div>
                              <div className="flex flex-wrap gap-1.5">
                                {(node.node_type === 'video'
                                  ? getVideoAspectRatios(config.model || '')
                                  : ASPECT_RATIOS
                                ).map((r) => {
                                  const selected = config.aspect_ratio === r;
                                  return (
                                    <button
                                      key={r}
                                      onClick={() => updateConfig({ aspect_ratio: r })}
                                      className={`px-2.5 py-1.5 rounded-lg text-[10px] font-medium border transition-all duration-150 ${
                                        selected
                                          ? 'border-accent bg-accent/10 text-accent ring-1 ring-accent/30'
                                          : 'border-panel-border bg-theme-input text-theme-sub hover:border-accent/40 hover:bg-panel-hover'
                                      }`}
                                    >
                                      {r}
                                    </button>
                                  );
                                })}
                              </div>
                            </div>
                          )}

                          {/* 图片分辨率 — 仅 Seedream 模型 */}
                          {(node.node_type === 'image' || node.node_type === 'storyboard' || node.node_type === 'character' || node.node_type === 'scene') && isSeedreamModel(config.model || '') && (
                            <div className="mb-3">
                              <div className="text-[10px] text-theme-sub font-medium mb-1.5 flex items-center gap-1">
                                <Monitor size={10} /> 图片分辨率
                              </div>
                              <div className="flex flex-wrap gap-1.5">
                                {IMAGE_RESOLUTIONS.map((r) => {
                                  const selected = config.resolution === r;
                                  return (
                                    <button
                                      key={r}
                                      onClick={() => updateConfig({ resolution: r })}
                                      className={`px-2.5 py-1.5 rounded-lg text-[10px] font-medium border transition-all duration-150 ${
                                        selected
                                          ? 'border-accent bg-accent/10 text-accent ring-1 ring-accent/30'
                                          : 'border-panel-border bg-theme-input text-theme-sub hover:border-accent/40 hover:bg-panel-hover'
                                      }`}
                                    >
                                      {r}
                                    </button>
                                  );
                                })}
                              </div>
                            </div>
                          )}

                          {/* 视频专属：时长 + 分辨率 + 声音 + 水印 */}
                          {node.node_type === 'video' && (
                            <>
                              <div className="mb-3">
                                <div className="text-[10px] text-theme-sub font-medium mb-1.5 flex items-center gap-1">
                                  <Clock size={10} /> 时长
                                </div>
                                <div className="flex flex-wrap gap-1.5">
                                  {getVideoDurations(config.model || '').map((d) => {
                                    const selected = config.duration === d;
                                    return (
                                      <button
                                        key={d}
                                        onClick={() => updateConfig({ duration: d })}
                                        className={`px-2.5 py-1.5 rounded-lg text-[10px] font-medium border transition-all duration-150 ${
                                          selected
                                            ? 'border-accent bg-accent/10 text-accent ring-1 ring-accent/30'
                                            : 'border-panel-border bg-theme-input text-theme-sub hover:border-accent/40 hover:bg-panel-hover'
                                        }`}
                                      >
                                        {d}s
                                      </button>
                                    );
                                  })}
                                </div>
                              </div>

                              <div className="mb-3">
                                <div className="text-[10px] text-theme-sub font-medium mb-1.5 flex items-center gap-1">
                                  <Monitor size={10} /> 视频分辨率
                                </div>
                                <div className="flex flex-wrap gap-1.5">
                                  {getVideoResolutions(config.model || '').map((r) => {
                                    const selected = config.resolution === r;
                                    return (
                                      <button
                                        key={r}
                                        onClick={() => updateConfig({ resolution: r })}
                                        className={`px-2.5 py-1.5 rounded-lg text-[10px] font-medium border transition-all duration-150 ${
                                          selected
                                            ? 'border-accent bg-accent/10 text-accent ring-1 ring-accent/30'
                                            : 'border-panel-border bg-theme-input text-theme-sub hover:border-accent/40 hover:bg-panel-hover'
                                        }`}
                                      >
                                        {r}
                                      </button>
                                    );
                                  })}
                                </div>
                              </div>

                              {supportsVideoSound(config.model || '') && (
                                <div className="mb-3">
                                  <div className="text-[10px] text-theme-sub font-medium mb-1.5 flex items-center gap-1">
                                    <Volume2 size={10} /> 声音
                                  </div>
                                  <div className="flex gap-1.5">
                                    <button
                                      onClick={() => updateConfig({ sound: true })}
                                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-medium border transition-all duration-150 ${
                                        config.sound
                                          ? 'border-accent bg-accent/10 text-accent ring-1 ring-accent/30'
                                          : 'border-panel-border bg-theme-input text-theme-sub hover:border-accent/40 hover:bg-panel-hover'
                                      }`}
                                    >
                                      <Volume2 size={11} /> 有声
                                    </button>
                                    <button
                                      onClick={() => updateConfig({ sound: false })}
                                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-medium border transition-all duration-150 ${
                                        !config.sound
                                          ? 'border-accent bg-accent/10 text-accent ring-1 ring-accent/30'
                                          : 'border-panel-border bg-theme-input text-theme-sub hover:border-accent/40 hover:bg-panel-hover'
                                      }`}
                                    >
                                      <Volume2 size={11} className="opacity-40" /> 无声
                                    </button>
                                  </div>
                                </div>
                              )}

                              {supportsVideoWatermark(config.model || '') && (
                                <div className="mb-3">
                                  <div className="text-[10px] text-theme-sub font-medium mb-1.5 flex items-center gap-1">
                                    <Droplet size={10} /> 水印
                                  </div>
                                  <div className="flex gap-1.5">
                                    <button
                                      onClick={() => updateConfig({ watermark: true })}
                                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-medium border transition-all duration-150 ${
                                        config.watermark
                                          ? 'border-accent bg-accent/10 text-accent ring-1 ring-accent/30'
                                          : 'border-panel-border bg-theme-input text-theme-sub hover:border-accent/40 hover:bg-panel-hover'
                                      }`}
                                    >
                                      <Droplet size={11} /> 有水印
                                    </button>
                                    <button
                                      onClick={() => updateConfig({ watermark: false })}
                                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-medium border transition-all duration-150 ${
                                        !config.watermark
                                          ? 'border-accent bg-accent/10 text-accent ring-1 ring-accent/30'
                                          : 'border-panel-border bg-theme-input text-theme-sub hover:border-accent/40 hover:bg-panel-hover'
                                      }`}
                                    >
                                      <Droplet size={11} className="opacity-40" /> 无水印
                                    </button>
                                  </div>
                                </div>
                              )}

                              {supportsStartEndFrame(config.model || '') && (
                                <div className="mb-1">
                                  <div className="text-[10px] text-theme-sub font-medium mb-1.5 flex items-center gap-1">
                                    <FlipHorizontal size={10} /> 首尾帧
                                  </div>
                                  <div className="flex gap-1.5">
                                    <button
                                      onClick={() => updateConfig({ start_end_frame: true })}
                                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-medium border transition-all duration-150 ${
                                        config.start_end_frame
                                          ? 'border-accent bg-accent/10 text-accent ring-1 ring-accent/30'
                                          : 'border-panel-border bg-theme-input text-theme-sub hover:border-accent/40 hover:bg-panel-hover'
                                      }`}
                                    >
                                      <FlipHorizontal size={11} /> 启用
                                    </button>
                                    <button
                                      onClick={() => updateConfig({ start_end_frame: false })}
                                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-medium border transition-all duration-150 ${
                                        !config.start_end_frame
                                          ? 'border-accent bg-accent/10 text-accent ring-1 ring-accent/30'
                                          : 'border-panel-border bg-theme-input text-theme-sub hover:border-accent/40 hover:bg-panel-hover'
                                      }`}
                                    >
                                      <FlipHorizontal size={11} className="opacity-40" /> 关闭
                                    </button>
                                  </div>
                                  <div className="text-[9px] text-theme-hint mt-1">
                                    启用后前两张参考图分别作为首帧和尾帧生成视频
                                  </div>
                                </div>
                              )}
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  </>
                )}

                {/* 预设功能菜单 */}
                <div className="w-px h-5 bg-panel-border shrink-0" />
                <PresetMenu node={node} />

                {uploading && <Loader2 size={16} className="animate-spin text-accent ml-2" />}
                <input ref={fileInputRef} type="file" className="hidden" onChange={handleFileChange} />
              </div>

              {/* 发送 / 生成 + 积分预估：生成中保持显示但禁用 */}
              <div className="flex items-center gap-1.5 shrink-0">
                {estimatedCost > 0 && node.status !== 'processing' && (
                  <div className="flex items-center gap-0.5 text-[11px] text-warning px-1" title={`预计消耗 ${estimatedCost} 积分`}>
                    <Coins size={12} />
                    {estimatedCost}
                  </div>
                )}
                <button
                  className={`w-9 h-9 rounded-full flex items-center justify-center transition-colors shadow-soft ${
                    node.status === 'processing'
                      ? 'bg-theme-input text-theme-hint cursor-not-allowed'
                      : 'btn-primary'
                  }`}
                  onClick={node.status === 'processing' ? undefined : handleRegenerate}
                  disabled={node.status === 'processing'}
                  title={node.status === 'success' ? '重新生成' : '生成'}
                >
                  {node.status === 'processing' ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* 资产选择器 */}
        {showAssetPicker && (
          <div className="absolute inset-x-0 bottom-0 max-h-[60%] rounded-t-2xl rounded-b-3xl border-t border-panel-border shadow-soft-lg z-50 flex flex-col panel-solid">
            <div className="h-10 border-b border-panel-border flex items-center justify-between px-3 shrink-0">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-theme-main">选择引用资产</span>
                <button
                  className={`flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[9px] border transition-colors ${
                    crossProject
                      ? 'bg-accent/20 border-accent text-accent'
                      : 'bg-transparent border-panel-border text-theme-sub hover:border-accent/30'
                  }`}
                  onClick={() => { setCrossProject((v) => !v); setTimeout(() => openAssetPicker(), 0); }}
                  title={crossProject ? '当前显示所有项目资产' : '当前仅显示本项目资产，点击切换'}
                >
                  <Globe size={9} />
                  {crossProject ? '全部' : '本项目'}
                </button>
              </div>
              <button className="p-1 rounded-full hover:bg-panel-hover text-theme-sub" onClick={() => setShowAssetPicker(false)}>
                <X size={14} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-2 space-y-1">
              {assetsLoading ? (
                <div className="text-center text-theme-sub text-xs py-6">加载中...</div>
              ) : assets.length === 0 ? (
                <div className="text-center text-theme-sub text-xs py-6">暂无可用资产</div>
              ) : (
                assets.map((asset) => {
                  const selected = (config.reference_asset_ids || []).includes(asset.id);
                  return (
                    <button
                      key={asset.id}
                      className={`w-full flex items-center gap-2 p-2 rounded-xl text-left border transition-colors ${
                        selected
                          ? 'border-accent bg-accent/10'
                          : 'border-panel-border bg-theme-input hover:border-accent/50'
                      }`}
                      onClick={() => (selected ? detachAsset(asset.id) : attachAsset(asset))}
                    >
                      <div className="w-8 h-8 rounded-lg bg-panel-hover flex items-center justify-center shrink-0 overflow-hidden">
                        {asset.file_url?.match(/\.(jpg|jpeg|png|webp|gif|svg)(\?|$)/i) ? (
                          <img src={asset.thumbnail_url || asset.file_url} alt="" className="w-full h-full object-cover" />
                        ) : (
                          <span className="text-[10px] text-theme-muted">{asset.asset_type[0]}</span>
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-[11px] font-semibold text-theme-main truncate">{asset.name}</div>
                        <div className="text-[9px] text-theme-sub">{asset.asset_type}</div>
                      </div>
                      {selected && <Check size={14} className="text-accent" />}
                    </button>
                  );
                })
              )}
            </div>
          </div>
        )}

      </div>

      {/* 提示词放大编辑弹窗 */}
      {expandedPrompt && (
        <div
          className="fixed inset-0 z-[300] flex items-center justify-center bg-black/60 no-pan"
          onClick={() => setExpandedPrompt(false)}
          onKeyDown={(e) => { if (e.key === 'Escape') setExpandedPrompt(false); }}
        >
          <div
            className="w-[640px] max-w-[90vw] rounded-3xl shadow-soft-lg flex flex-col overflow-hidden panel-solid border border-panel-border"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="h-12 flex items-center justify-between px-4 border-b border-panel-border">
              <span className="text-sm font-semibold text-theme-main">编辑提示词</span>
              <button
                className="p-1.5 rounded-full hover:bg-panel-hover text-theme-sub"
                onClick={() => setExpandedPrompt(false)}
              >
                <X size={16} />
              </button>
            </div>
            <div className="p-4">
              <textarea
                className="w-full min-h-[320px] bg-theme-input rounded-2xl p-4 text-[14px] text-theme-main placeholder:text-theme-hint focus:outline-none resize-none leading-relaxed border border-transparent focus:border-accent"
                value={expandedPromptValue}
                onChange={(e) => setExpandedPromptValue(e.target.value)}
                placeholder="输入描述词..."
              />
            </div>
            <div className="px-4 py-3 border-t border-panel-border flex justify-end gap-2">
              <button
                className="px-4 py-2 rounded-full text-[12px] text-theme-muted hover:bg-panel-hover transition-colors"
                onClick={() => setExpandedPrompt(false)}
              >
                取消
              </button>
              <button
                className="px-5 py-2 rounded-full text-[12px] btn-primary"
                onClick={confirmExpandedPrompt}
              >
                确认
              </button>
            </div>
          </div>
        </div>
      )}

      {lightbox && (
        <div
          className="fixed inset-0 z-[300] flex items-center justify-center bg-black/80 no-pan"
          onClick={() => setLightbox(null)}
          onKeyDown={(e) => { if (e.key === 'Escape') setLightbox(null); }}
        >
          <div className="absolute top-4 right-4 flex items-center gap-2">
            <button
              className="p-2 rounded-full bg-black/50 text-white hover:bg-black/70 transition-colors"
              title="下载"
              onClick={(e) => { e.stopPropagation(); downloadLightbox(lightbox.url, lightbox.type); }}
            >
              <Download size={20} />
            </button>
            <button
              className="p-2 rounded-full bg-black/50 text-white hover:bg-black/70 transition-colors"
              title="关闭"
              onClick={(e) => { e.stopPropagation(); setLightbox(null); }}
            >
              <X size={20} />
            </button>
          </div>
          {lightbox.type === 'image' ? (
            <img
              src={lightbox.url}
              alt=""
              className="max-w-[90vw] max-h-[90vh] object-contain rounded-lg shadow-soft-lg"
              onClick={(e) => e.stopPropagation()}
            />
          ) : (
            <video
              src={lightbox.url}
              controls
              autoPlay
              className="max-w-[90vw] max-h-[90vh] rounded-lg shadow-soft-lg"
              onClick={(e) => e.stopPropagation()}
            />
          )}
        </div>
      )}
    </>
  );
}
