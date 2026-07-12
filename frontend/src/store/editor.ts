import { create } from 'zustand';
import type { Canvas, CanvasNode, CanvasEdge, WSMessage, CanvasListItem } from '@/types';
import { api } from '@/utils/api';
import type { ModelPricing, EnabledModel } from '@/utils/api';
import { setEnabledModelIds, loadRuntimeModels } from '@/utils/model-config';

interface EditorState {
  canvas: Canvas | null;
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  connectingFrom: string | null;
  canvasList: CanvasListItem[];
  modelPricing: ModelPricing[];
  enabledModels: EnabledModel[];
  loading: boolean;
  wsConnected: boolean;
  showAssetPanel: boolean;
  showSnapshotPanel: boolean;
  showCanvasList: boolean;
  error: string | null;

  setCanvas: (canvas: Canvas) => void;
  clearCanvas: () => void;
  setSelectedNode: (id: string | null) => void;
  setSelectedEdge: (id: string | null) => void;
  setConnectingFrom: (id: string | null) => void;
  setLoading: (v: boolean) => void;
  setWsConnected: (v: boolean) => void;
  toggleAssetPanel: () => void;
  toggleSnapshotPanel: () => void;
  setShowCanvasList: (v: boolean) => void;
  setError: (msg: string | null) => void;
  loadModelPricing: () => Promise<void>;
  loadEnabledModels: () => Promise<void>;
  loadRuntimeModels: () => Promise<void>;

  loadCanvasList: (forceRefresh?: boolean) => Promise<void>;
  loadCanvas: (id: string) => Promise<void>;
  createNewCanvas: (name: string) => Promise<string>;
  deleteCanvas: (id: string) => Promise<void>;
  addNode: (nodeType: string, x: number, y: number) => Promise<void>;
  updateNodePos: (id: string, x: number, y: number) => void;
  updateNodeData: (id: string, data: Partial<CanvasNode>) => Promise<void>;
  deleteNode: (id: string) => Promise<void>;
  addEdge: (sourceId: string, targetId: string) => Promise<void>;
  updateEdgeType: (id: string, edgeType: CanvasEdge['edge_type']) => Promise<void>;
  deleteEdge: (id: string) => Promise<void>;
  applyAssetToSelectedNode: (asset: { id: string; file_url: string; asset_type: string; meta?: Record<string, unknown>; name: string }) => Promise<void>;
  handleWSMessage: (msg: WSMessage) => void;
  triggerGenerate: (nodeId: string, count?: number, config?: Record<string, unknown>) => Promise<void>;
}

export const useEditorStore = create<EditorState>((set, get) => ({
  canvas: null,
  selectedNodeId: null,
  selectedEdgeId: null,
  connectingFrom: null,
  canvasList: [],
  modelPricing: [],
  enabledModels: [],
  loading: false,
  wsConnected: false,
  showAssetPanel: false,
  showSnapshotPanel: false,
  showCanvasList: false,
  error: null,

  setCanvas: (canvas) => set({ canvas }),
  clearCanvas: () => { set({ canvas: null, selectedNodeId: null, selectedEdgeId: null, connectingFrom: null }); localStorage.removeItem('currentCanvasId'); },
  setSelectedNode: (id) => set({ selectedNodeId: id, selectedEdgeId: null, connectingFrom: null }),
  setSelectedEdge: (id) => set({ selectedEdgeId: id, selectedNodeId: null, connectingFrom: null }),
  setConnectingFrom: (id) => set({ connectingFrom: id }),
  setLoading: (v) => set({ loading: v }),
  setWsConnected: (v) => set({ wsConnected: v }),
  toggleAssetPanel: () => set((s) => ({ showAssetPanel: !s.showAssetPanel, showSnapshotPanel: false })),
  toggleSnapshotPanel: () => set((s) => ({ showSnapshotPanel: !s.showSnapshotPanel, showAssetPanel: false })),
  setShowCanvasList: (v) => set({ showCanvasList: v }),
  setError: (msg) => set({ error: msg }),

  loadModelPricing: async () => {
    try {
      const pricing = await api.getModelPricing();
      set({ modelPricing: pricing });
    } catch {
      // 静默失败，不影响画布加载
    }
  },

  loadEnabledModels: async () => {
    try {
      const models = await api.getEnabledModels();
      set({ enabledModels: models });
      setEnabledModelIds(models.map(m => m.model_id));
    } catch {
      // 静默失败，使用硬编码列表作为降级
    }
  },

  loadRuntimeModels: async () => {
    await loadRuntimeModels();
  },

  loadCanvasList: async (forceRefresh = false) => {
    // #14: sessionStorage 缓存画布列表，TTL 30s
    const CACHE_KEY = 'canvasListCache';
    const TTL = 30_000;
    if (!forceRefresh) {
      try {
        const raw = sessionStorage.getItem(CACHE_KEY);
        if (raw) {
          const cached = JSON.parse(raw);
          if (cached.ts && Date.now() - cached.ts < TTL && Array.isArray(cached.list)) {
            set({ canvasList: cached.list });
            return;
          }
        }
      } catch { /* ignore */ }
    }
    try {
      const list = await api.listCanvases();
      set({ canvasList: list });
      sessionStorage.setItem(CACHE_KEY, JSON.stringify({ ts: Date.now(), list }));
    } catch (e) {
      set({ error: '加载画布列表失败' });
    }
  },

  loadCanvas: async (id) => {
    set({ loading: true });
    try {
      const canvas = await api.getCanvas(id);
      set({ canvas, selectedNodeId: null, selectedEdgeId: null });
      localStorage.setItem('currentCanvasId', id);
    } catch (e) {
      set({ canvas: null, error: '加载画布失败' });
      localStorage.removeItem('currentCanvasId');
    } finally {
      set({ loading: false });
    }
  },

  createNewCanvas: async (name) => {
    const canvas = await api.createCanvas(name);
    const c = await api.getCanvas(canvas.id);
    set({ canvas: c, selectedNodeId: null });
    await get().loadCanvasList(true); // #14: 新建画布后强制刷新缓存
    return canvas.id;
  },

  deleteCanvas: async (id) => {
    try {
      await api.deleteCanvas(id);
      const { canvas } = get();
      if (canvas?.id === id) {
        set({ canvas: null, selectedNodeId: null, selectedEdgeId: null });
        localStorage.removeItem('currentCanvasId');
      }
      await get().loadCanvasList(true); // #14: 删除画布后强制刷新缓存
      // 同时清除该画布的缩略图缓存
      try {
        const thumbRaw = sessionStorage.getItem('canvasThumbsCache');
        if (thumbRaw) {
          const thumbs = JSON.parse(thumbRaw);
          delete thumbs[id];
          sessionStorage.setItem('canvasThumbsCache', JSON.stringify(thumbs));
        }
      } catch { /* ignore */ }
    } catch (e: any) {
      set({ error: e.message || '删除项目失败' });
      throw e;
    }
  },

  addNode: async (nodeType, x, y) => {
    const { canvas } = get();
    if (!canvas) return;
    const typeLabels: Record<string, string> = {
      script: '剧本', character: '角色', scene: '场景', storyboard: '分镜',
      image: '图片', video: '视频', audio: '音频', group: '分组',
    };
    // 基于同类型现有节点的最大序号 +1，避免删除后重名
    const labelBase = typeLabels[nodeType] || '节点';
    const re = new RegExp(`^${labelBase.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s+(\\d+)$`);
    let maxIdx = 0;
    for (const n of canvas.nodes) {
      if (n.node_type !== nodeType) continue;
      const m = (n.title || '').match(re);
      if (m) maxIdx = Math.max(maxIdx, parseInt(m[1], 10));
    }
    try {
      const node = await api.createNode({
        canvas_id: canvas.id,
        node_type: nodeType as CanvasNode['node_type'],
        title: `${labelBase} ${maxIdx + 1}`,
        x, y,
      });
      set({ canvas: { ...canvas, nodes: [...canvas.nodes, node] } });
    } catch (e) {
      set({ error: '创建节点失败' });
    }
  },

  updateNodePos: (id, x, y) => {
    const { canvas } = get();
    if (!canvas) return;
    set({
      canvas: {
        ...canvas,
        nodes: canvas.nodes.map((n) => (n.id === id ? { ...n, x, y } : n)),
      },
    });
  },

  updateNodeData: async (id, data) => {
    set((s) => ({
      canvas: s.canvas
        ? { ...s.canvas, nodes: s.canvas.nodes.map((n) => (n.id === id ? { ...n, ...data } : n)) }
        : s.canvas,
    }));
    try {
      await api.updateNode(id, data);
    } catch (e) {
      set({ error: '更新节点失败' });
    }
  },

  deleteNode: async (id) => {
    const { canvas } = get();
    if (!canvas) return;
    set({
      canvas: {
        ...canvas,
        nodes: canvas.nodes.filter((n) => n.id !== id),
        edges: canvas.edges.filter((e) => e.source_node_id !== id && e.target_node_id !== id),
      },
      selectedNodeId: null,
    });
    try {
      await api.deleteNode(id);
    } catch (e) {
      set({ error: '删除节点失败' });
    }
  },

  addEdge: async (sourceId, targetId) => {
    const { canvas } = get();
    if (!canvas || sourceId === targetId) return;
    const source = canvas.nodes.find((n) => n.id === sourceId);
    const target = canvas.nodes.find((n) => n.id === targetId);
    let edgeType: CanvasEdge['edge_type'] = 'default';
    if (source && target) {
      const s = source.node_type;
      const t = target.node_type;
      // 视觉媒体节点 → 可生成视觉节点 = 引用关系（用源节点结果图作为参考）
      const visualSourceTypes = ['character', 'scene', 'storyboard', 'image'];
      const generatableTargetTypes = ['storyboard', 'image', 'video'];
      if (visualSourceTypes.includes(s) && generatableTargetTypes.includes(t)) {
        edgeType = 'reference';
      }
    }
    const exists = canvas.edges.some(
      (e) =>
        e.source_node_id === sourceId &&
        e.target_node_id === targetId &&
        e.edge_type === edgeType
    );
    if (exists) return;
    try {
      const edge = await api.createEdge({
        canvas_id: canvas.id,
        source_node_id: sourceId,
        target_node_id: targetId,
        edge_type: edgeType,
      });
      set({ canvas: { ...canvas, edges: [...canvas.edges, edge] } });
    } catch (e) {
      set({ error: '创建连线失败' });
    }
  },

  updateEdgeType: async (id, edgeType) => {
    const { canvas } = get();
    if (!canvas) return;
    set({
      canvas: {
        ...canvas,
        edges: canvas.edges.map((e) => (e.id === id ? { ...e, edge_type: edgeType } : e)),
      },
    });
    try {
      await api.updateEdge(id, { edge_type: edgeType });
    } catch (e) {
      set({ error: '更新连线类型失败' });
    }
  },

  deleteEdge: async (id) => {
    const { canvas } = get();
    if (!canvas) return;
    await api.deleteEdge(id);
    set({
      canvas: { ...canvas, edges: canvas.edges.filter((e) => e.id !== id) },
      selectedEdgeId: null,
    });
  },

  applyAssetToSelectedNode: async (asset) => {
    const { canvas, selectedNodeId } = get();
    if (!canvas || !selectedNodeId) {
      set({ error: '请先在画布上选中一个分镜节点' });
      return;
    }
    const target = canvas.nodes.find((n) => n.id === selectedNodeId);
    if (!target) return;
    if (target.node_type !== 'storyboard' && target.node_type !== 'image' && target.node_type !== 'video') {
      set({ error: '请先选中一个分镜或图片节点' });
      return;
    }
    const cfg = (target.config || {}) as Record<string, unknown>;
    const refImages = new Set<string>((cfg.reference_images as string[]) || []);
    const refAssetIds = new Set<string>((cfg.reference_asset_ids as string[]) || []);
    if (asset.file_url) refImages.add(asset.file_url);
    refAssetIds.add(asset.id);
    const newConfig = { ...cfg, reference_images: Array.from(refImages), reference_asset_ids: Array.from(refAssetIds) };
    set({
      canvas: {
        ...canvas,
        nodes: canvas.nodes.map((n) => (n.id === selectedNodeId ? { ...n, config: newConfig } : n)),
      },
    });
    try {
      await api.updateNode(selectedNodeId, { config: newConfig });
    } catch (e) {
      set({ error: '注入参考图失败' });
    }
    const sourceNodeId = asset.meta?.node_id as string | undefined;
    if (sourceNodeId && sourceNodeId !== selectedNodeId) {
      const sourceExists = canvas.nodes.some((n) => n.id === sourceNodeId);
      if (sourceExists) {
        const edgeExists = canvas.edges.some(
          (e) => e.source_node_id === sourceNodeId && e.target_node_id === selectedNodeId && e.edge_type === 'reference'
        );
        if (!edgeExists) {
          try {
            const edge = await api.createEdge({
              canvas_id: canvas.id,
              source_node_id: sourceNodeId,
              target_node_id: selectedNodeId,
              edge_type: 'reference',
            });
            set({ canvas: { ...get().canvas!, edges: [...get().canvas!.edges, edge] } });
          } catch (e) {
            // edge 创建失败不阻塞
          }
        }
      }
    }
  },

  handleWSMessage: (msg) => {
    const { canvas } = get();
    if (!canvas || msg.canvas_id !== canvas.id) return;

    const applyNodeUpdate = (nodeId: string) => (n: CanvasNode) => {
      if (n.id !== nodeId) return n;
      // WS 推送的是 task.status（queued/running/success/failed/retrying/cancelled），
      // 需要映射为前端 NodeStatus（pending/processing/success/failed）
      const rawStatus = msg.status as string | undefined;
      let incomingStatus: CanvasNode['status'] = n.status;
      if (rawStatus === 'queued' || rawStatus === 'running' || rawStatus === 'retrying' || rawStatus === 'pending') {
        incomingStatus = 'processing';
      } else if (rawStatus === 'success') {
        incomingStatus = 'success';
      } else if (rawStatus === 'failed' || rawStatus === 'cancelled') {
        incomingStatus = 'failed';
      }
      return {
        ...n,
        status: incomingStatus,
        progress: msg.progress ?? n.progress,
        error_msg: incomingStatus === 'failed' ? (msg.error || n.error_msg) : undefined,
        result_url: (msg.result?.url as string) || n.result_url,
        thumbnail_url: (msg.result?.thumbnail_url as string) || n.thumbnail_url,
      };
    };

    if ((msg.type === 'task_update' || msg.type === 'node_status') && msg.node_id) {
      set({
        canvas: { ...canvas, nodes: canvas.nodes.map(applyNodeUpdate(msg.node_id)) },
      });
    }
  },

  triggerGenerate: async (nodeId, count = 1, overrideConfig?: Record<string, unknown>) => {
    const { canvas } = get();
    if (!canvas) return;
    const node = canvas.nodes.find((n) => n.id === nodeId);
    if (!node) return;
    if (node.status === 'processing') return;
    // 优先使用调用方传入的 config（来自 PropertyPopup 本地 state），
    // 避免 PATCH 竞态或 WS 推送覆盖导致后端读到的 node.config 仍是旧值
    const nodeConfig = overrideConfig || (node.config || {}) as Record<string, unknown>;
    set((s) => ({
      canvas: s.canvas
        ? {
            ...s.canvas,
            nodes: s.canvas.nodes.map((n) =>
              n.id === nodeId ? { ...n, status: 'processing', progress: 0, error_msg: undefined } : n
            ),
          }
        : s.canvas,
    }));
    try {
      await api.nodeAction(nodeId, 'generate', node.prompt, node.style, count, nodeConfig);
    } catch (e: any) {
      set((s) => ({
        canvas: s.canvas
          ? {
              ...s.canvas,
              nodes: s.canvas.nodes.map((n) =>
                n.id === nodeId ? { ...n, status: 'failed', error_msg: e?.message } : n
              ),
            }
          : s.canvas,
      }));
      set({ error: e?.message || '生成失败' });
    }
  },
}));
