import { useRef, useState, useCallback, useEffect, useMemo } from 'react';
import { Bot, Sparkles, Maximize, Focus, Image as ImageIcon, FileText, Film, User, MapPin, Feather, Clapperboard, Volume2, Loader2 } from 'lucide-react';
import { useEditorStore } from '@/store/editor';
import { NodeCard } from './NodeCard';
import { NodePropertyPopup } from './NodePropertyPopup';
import { type GridOverlayMode } from './NodeActionBar';
import { MaskEditor } from './MaskEditor';
import { CinematicQuickPanel } from './CinematicQuickPanel';
import { api } from '@/utils/api';
import type { CanvasNode, NodeConfig } from '@/types';

interface CanvasProps {
  onOpenAgent?: () => void;
}

interface DragLine {
  fromX: number;
  fromY: number;
  toX: number;
  toY: number;
}

const NODE_DEFAULT_WIDTH = 180;
const NODE_DEFAULT_HEIGHT = 80;

function bezierPath(x1: number, y1: number, x2: number, y2: number): string {
  const dx = Math.abs(x2 - x1) * 0.5;
  const c1x = x1 + dx;
  const c2x = x2 - dx;
  return `M ${x1} ${y1} C ${c1x} ${y1}, ${c2x} ${y2}, ${x2} ${y2}`;
}

function getNodeCenter(node: { x: number; y: number; width: number; height: number }) {
  return { x: node.x + node.width / 2, y: node.y + node.height / 2 };
}

// 根据源/目标节点相对位置动态选择起点/终点边（右/左/下/上），避免连线穿过节点本身
function getEdgeEndpoints(
  src: { x: number; y: number; width: number; height: number },
  tgt: { x: number; y: number; width: number; height: number }
): { sx: number; sy: number; tx: number; ty: number } {
  const srcCx = src.x + src.width / 2;
  const srcCy = src.y + src.height / 2;
  const tgtCx = tgt.x + tgt.width / 2;
  const tgtCy = tgt.y + tgt.height / 2;
  const dx = tgtCx - srcCx;
  const dy = tgtCy - srcCy;
  if (Math.abs(dx) >= Math.abs(dy)) {
    // 水平为主
    if (dx >= 0) {
      return { sx: src.x + src.width, sy: srcCy, tx: tgt.x, ty: tgtCy };
    }
    return { sx: src.x, sy: srcCy, tx: tgt.x + tgt.width, ty: tgtCy };
  }
  // 垂直为主
  if (dy >= 0) {
    return { sx: srcCx, sy: src.y + src.height, tx: tgtCx, ty: tgt.y };
  }
  return { sx: srcCx, sy: src.y, tx: tgtCx, ty: tgt.y + tgt.height };
}

export function Canvas({ onOpenAgent }: CanvasProps) {
  const canvasRef = useRef<HTMLDivElement>(null);
  const { canvas, selectedNodeId, selectedEdgeId, connectingFrom, setSelectedNode, setSelectedEdge, setConnectingFrom, addNode, addEdge, updateEdgeType, updateNodePos, updateNodeData, deleteNode, triggerGenerate, deleteEdge, loadModelPricing, loadEnabledModels, loadRuntimeModels } = useEditorStore();
  const [dragLine, setDragLine] = useState<DragLine | null>(null);
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number } | null>(null);
  const [edgeContextMenu, setEdgeContextMenu] = useState<{ x: number; y: number; edgeId: string } | null>(null);
  const [panCursor, setPanCursor] = useState<'grab' | 'grabbing'>('grab');
  const [pasting, setPasting] = useState(false);
  // 网格叠加模式（九宫格/十二宫格）
  const [gridMode, setGridMode] = useState<GridOverlayMode>('none');
  // 局部重绘 MaskEditor
  const [maskEditorNodeId, setMaskEditorNodeId] = useState<string | null>(null);
  // 运镜/影视参数面板
  const [cinematicNodeId, setCinematicNodeId] = useState<string | null>(null);
  // 完整属性面板（点击节点同时显示 ActionBar 和 PropertyPopup）
  const [showPropertyPopup, setShowPropertyPopup] = useState(true);
  // 快捷上传：隐藏 file input，记录目标节点 ID
  const quickUploadRef = useRef<HTMLInputElement>(null);
  const [quickUploadNodeId, setQuickUploadNodeId] = useState<string | null>(null);
  // 快捷引用：直接打开 PropertyPopup 并触发引用按钮
  const [quickReferenceNodeId, setQuickReferenceNodeId] = useState<string | null>(null);
  // 维护节点实际渲染高度（由 NodeCard 通过 ResizeObserver 回写），用于计算连线终点
  const nodeHeightsRef = useRef<Map<string, number>>(new Map());
  const [, setHeightsTick] = useState(0); // 触发重渲染连线
  // 快捷上传：点击后打开文件选择器
  const handleQuickUpload = useCallback((nodeId: string) => {
    setQuickUploadNodeId(nodeId);
    // 确保 PropertyPopup 也打开，让用户看到上传结果
    setShowPropertyPopup(true);
    if (quickUploadRef.current) {
      quickUploadRef.current.accept = 'image/*';
      quickUploadRef.current.click();
    }
  }, []);

  // 快捷上传：文件选择后上传并注入参考图
  const handleQuickUploadChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !quickUploadNodeId || !canvas) return;
    try {
      const asset = await api.uploadAsset(file, {
        name: file.name,
        assetType: 'image',
        description: `快捷上传参考图`,
        canvasId: canvas.id,
      });
      // 注入到目标节点的 config 中
      const node = canvas.nodes.find((n) => n.id === quickUploadNodeId);
      if (node) {
        const cfg = (node.config || {}) as Record<string, unknown>;
        const refs = new Set<string>((cfg.reference_images as string[]) || []);
        refs.add(asset.file_url);
        const assetIds = new Set<string>((cfg.reference_asset_ids as string[]) || []);
        assetIds.add(asset.id);
        const newConfig = { ...cfg, reference_images: Array.from(refs), reference_asset_ids: Array.from(assetIds) };
        await api.updateNode(node.id, { config: newConfig });
        useEditorStore.setState((s) => ({
          canvas: s.canvas
            ? {
                ...s.canvas,
                nodes: s.canvas.nodes.map((n) =>
                  n.id === quickUploadNodeId ? { ...n, config: newConfig } : n
                ),
              }
            : s.canvas,
        }));
      }
    } catch {
      window.alert('上传参考图失败，请重试');
    } finally {
      setQuickUploadNodeId(null);
      e.target.value = '';
    }
  };

  // 快捷引用：打开 PropertyPopup（用户可在其中点击引用按钮）
  const handleQuickReference = useCallback((nodeId: string) => {
    setShowPropertyPopup(true);
    setQuickReferenceNodeId(nodeId);
  }, []);

  // 首次加载画布后自动 fit 一次，避免节点（尤其是右侧视频节点）超出视口
  const fittedCanvasIdRef = useRef<string | null>(null);

  const handleNodeHeightChange = useCallback((id: string, height: number) => {
    const prev = nodeHeightsRef.current.get(id);
    if (prev !== height) {
      nodeHeightsRef.current.set(id, height);
      setHeightsTick((t) => t + 1);
    }
  }, []);

  // refs mirror scale/offset so high-frequency interactions (pan/wheel) can
  // update the DOM directly without triggering React re-renders.
  const scaleRef = useRef(scale);
  const offsetRef = useRef(offset);
  const transformRef = useRef<HTMLDivElement>(null);
  const canvasDataRef = useRef(canvas);
  const connectingFromRef = useRef(connectingFrom);

  const isPanning = useRef(false);
  const panStart = useRef({ x: 0, y: 0, ox: 0, oy: 0 });
  const pendingPositions = useRef<Map<string, { x: number; y: number }>>(new Map());
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const applyTransform = useCallback(() => {
    const el = transformRef.current;
    if (!el) return;
    el.style.transform = `translate(${offsetRef.current.x}px, ${offsetRef.current.y}px) scale(${scaleRef.current})`;
  }, []);

  useEffect(() => {
    canvasDataRef.current = canvas;
  }, [canvas]);

  // 切换选中节点时重置子面板：同时显示 ActionBar + PropertyPopup
  useEffect(() => {
    setShowPropertyPopup(true);
    setMaskEditorNodeId(null);
    setCinematicNodeId(null);
    setGridMode('none');
  }, [selectedNodeId]);

  useEffect(() => {
    connectingFromRef.current = connectingFrom;
  }, [connectingFrom]);

// apply transform once on mount (transform is managed via DOM, not JSX)
useEffect(() => {
applyTransform();
}, [applyTransform]);

// 加载模型定价（用于 NodeCard 预估扣费）、已启用模型列表（用于过滤已禁用模型）
// 以及运行时模型配置（从后端 .env 同步，动态更新前端模型列表）
useEffect(() => {
loadModelPricing();
loadEnabledModels();
loadRuntimeModels();
}, [loadModelPricing, loadEnabledModels, loadRuntimeModels]);



  const schedulePositionSave = useCallback(() => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      const positions = Array.from(pendingPositions.current.entries()).map(([id, pos]) => ({ id, x: pos.x, y: pos.y }));
      if (positions.length > 0) {
        import('@/utils/api').then(({ api }) => api.batchUpdatePositions(positions));
      }
      pendingPositions.current.clear();
    }, 500);
  }, []);

  const handlePositionChange = useCallback((id: string, x: number, y: number) => {
    updateNodePos(id, x, y);
    pendingPositions.current.set(id, { x, y });
    schedulePositionSave();
  }, [updateNodePos, schedulePositionSave]);

  const getViewportCenter = useCallback(() => {
    const rect = canvasRef.current?.getBoundingClientRect();
    const cw = rect?.width || 800;
    const ch = rect?.height || 600;
    return {
      x: (cw / 2 - offsetRef.current.x) / scaleRef.current - NODE_DEFAULT_WIDTH / 2,
      y: (ch / 2 - offsetRef.current.y) / scaleRef.current - NODE_DEFAULT_HEIGHT / 2,
    };
  }, []);

  const createImageNodeFromFile = useCallback(async (file: File, x?: number, y?: number) => {
    if (!canvas) return;
    setPasting(true);
    try {
      const asset = await api.uploadAsset(file, { assetType: 'image', name: file.name, canvasId: canvas.id });
      const pos = x !== undefined && y !== undefined ? { x, y } : getViewportCenter();
      await addNode('image', pos.x, pos.y);
      const { canvas: updated } = useEditorStore.getState();
      const newNode = updated?.nodes[updated.nodes.length - 1];
      if (newNode) {
        const imageUrl = asset.file_url;
        const thumbUrl = asset.thumbnail_url || imageUrl;
        await api.updateNode(newNode.id, {
          prompt: `参考图片：${asset.name}`,
          result_url: imageUrl,
          thumbnail_url: thumbUrl,
          // 只记录 asset_id 便于关联，不把自身图片写入 reference_images，
          // 避免生成时以自身为参考图
          config: { ...(newNode.config || {}), reference_asset_ids: [asset.id] },
        });
        useEditorStore.setState((s) => ({
          canvas: s.canvas
            ? {
                ...s.canvas,
                nodes: s.canvas.nodes.map((n) =>
                  n.id === newNode.id
                      ? {
                        ...n,
                        prompt: `参考图片：${asset.name}`,
                        result_url: imageUrl,
                        thumbnail_url: thumbUrl,
                        config: { ...(n.config || {}), reference_asset_ids: [asset.id] },
                      }
                    : n
                ),
              }
            : s.canvas,
        }));
      }
    } catch {
      window.alert('图片上传失败，请重试');
    } finally {
      setPasting(false);
    }
  }, [canvas, addNode, getViewportCenter]);

  const createScriptNodeFromText = useCallback(async (text: string, x?: number, y?: number) => {
    if (!canvas) return;
    const pos = x !== undefined && y !== undefined ? { x, y } : getViewportCenter();
    await addNode('script', pos.x, pos.y);
    const { canvas: updated } = useEditorStore.getState();
    const newNode = updated?.nodes[updated.nodes.length - 1];
    if (newNode) {
      await api.updateNode(newNode.id, { prompt: text });
      useEditorStore.setState((s) => ({
        canvas: s.canvas
          ? { ...s.canvas, nodes: s.canvas.nodes.map((n) => (n.id === newNode.id ? { ...n, prompt: text } : n)) }
          : s.canvas,
      }));
    }
  }, [canvas, addNode, getViewportCenter]);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const nodeType = e.dataTransfer.getData('nodeType');
    if (nodeType && canvasRef.current && canvas) {
      const rect = canvasRef.current.getBoundingClientRect();
      const x = (e.clientX - rect.left - offsetRef.current.x) / scaleRef.current - NODE_DEFAULT_WIDTH / 2;
      const y = (e.clientY - rect.top - offsetRef.current.y) / scaleRef.current - NODE_DEFAULT_HEIGHT / 2;
      addNode(nodeType, x, y);
      return;
    }

    // 文件 / 文本拖放
    const files = Array.from(e.dataTransfer.files);
    const text = e.dataTransfer.getData('text');
    if (!canvas) {
      window.alert('请先打开或创建一个画布');
      return;
    }
    if (canvasRef.current) {
      const rect = canvasRef.current.getBoundingClientRect();
      const dropX = (e.clientX - rect.left - offsetRef.current.x) / scaleRef.current - NODE_DEFAULT_WIDTH / 2;
      const dropY = (e.clientY - rect.top - offsetRef.current.y) / scaleRef.current - NODE_DEFAULT_HEIGHT / 2;
      files.forEach((file) => {
        if (file.type.startsWith('image/')) {
          createImageNodeFromFile(file, dropX, dropY);
        }
      });
      if (text) {
        createScriptNodeFromText(text, dropX + NODE_DEFAULT_WIDTH + 20, dropY);
      }
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  };

  const handleCanvasMouseDown = (e: React.MouseEvent) => {
    // 右键不触发平移，交给 contextmenu 处理
    if (e.button === 2) return;
    // 点击节点卡片、弹窗等 UI 区域不触发平移
    if ((e.target as HTMLElement).closest('.node-card, .no-pan')) return;
    setSelectedNode(null);
    setSelectedEdge(null);
    setConnectingFrom(null);
    isPanning.current = true;
    setPanCursor('grabbing');
    panStart.current = { x: e.clientX, y: e.clientY, ox: offsetRef.current.x, oy: offsetRef.current.y };
  };

  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY });
  };

  // close context menu on outside interaction
  useEffect(() => {
    if (!contextMenu) return;
    const close = (e: Event) => {
      // 右键事件来自画布内部时不关闭（由 handleContextMenu 更新位置）
      if (e.type === 'contextmenu' && canvasRef.current?.contains(e.target as Node)) {
        return;
      }
      setContextMenu(null);
    };
    window.addEventListener('click', close);
    window.addEventListener('contextmenu', close);
    return () => {
      window.removeEventListener('click', close);
      window.removeEventListener('contextmenu', close);
    };
  }, [contextMenu]);

  // close edge context menu on outside interaction
  useEffect(() => {
    if (!edgeContextMenu) return;
    const close = (e: Event) => {
      // 右键事件来自画布内部时不关闭
      if (e.type === 'contextmenu' && canvasRef.current?.contains(e.target as Node)) {
        return;
      }
      setEdgeContextMenu(null);
    };
    window.addEventListener('click', close);
    window.addEventListener('contextmenu', close);
    return () => {
      window.removeEventListener('click', close);
      window.removeEventListener('contextmenu', close);
    };
  }, [edgeContextMenu]);

  // 计算所有节点的包围盒（使用实际渲染高度）
  const getContentBounds = useCallback(() => {
    if (!canvas || canvas.nodes.length === 0) return null;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of canvas.nodes) {
      const actualH = nodeHeightsRef.current.get(n.id) ?? n.height ?? 160;
      const actualW = n.width || 240;
      minX = Math.min(minX, n.x);
      minY = Math.min(minY, n.y);
      maxX = Math.max(maxX, n.x + actualW);
      maxY = Math.max(maxY, n.y + actualH);
    }
    return { minX, minY, maxX, maxY };
  }, [canvas]);

  // 适合内容：固定 100% 缩放，计算偏移让所有节点居中
  const fitContent = useCallback(() => {
    const bounds = getContentBounds();
    if (!bounds) {
      offsetRef.current = { x: 0, y: 0 };
      scaleRef.current = 1;
      applyTransform();
      setOffset({ x: 0, y: 0 });
      setScale(1);
      return;
    }
    const { minX, minY, maxX, maxY } = bounds;
    const cw = canvasRef.current?.clientWidth || 800;
    const ch = canvasRef.current?.clientHeight || 600;
    const contentW = maxX - minX;
    const contentH = maxY - minY;
    // 100% 缩放，居中：让包围盒中心对齐视口中心
    scaleRef.current = 1;
    offsetRef.current = {
      x: (cw - contentW) / 2 - minX,
      y: (ch - contentH) / 2 - minY,
    };
    applyTransform();
    setScale(1);
    setOffset({ ...offsetRef.current });
  }, [getContentBounds, applyTransform]);

  // 重置视图：自适应缩放 + 居中，确保所有节点完整可见
  const resetView = useCallback(() => {
    const bounds = getContentBounds();
    if (!bounds) {
      offsetRef.current = { x: 0, y: 0 };
      scaleRef.current = 1;
      applyTransform();
      setOffset({ x: 0, y: 0 });
      setScale(1);
      return;
    }
    const { minX, minY, maxX, maxY } = bounds;
    const padding = 80;
    const cw = canvasRef.current?.clientWidth || 800;
    const ch = canvasRef.current?.clientHeight || 600;
    // 防止节点重叠时除零
    const contentW = Math.max(maxX - minX, 100) + padding * 2;
    const contentH = Math.max(maxY - minY, 100) + padding * 2;
    const newScale = Math.max(0.1, Math.min(2, Math.min(cw / contentW, ch / contentH)));
    const boxW = maxX - minX;
    const boxH = maxY - minY;
    offsetRef.current = {
      x: (cw - boxW * newScale) / 2 - minX * newScale,
      y: (ch - boxH * newScale) / 2 - minY * newScale,
    };
    scaleRef.current = newScale;
    applyTransform();
    setScale(newScale);
    setOffset({ ...offsetRef.current });
  }, [getContentBounds, applyTransform]);

  // 首次加载画布（或切换画布）且节点就绪后，自动 fit content 一次，避免右侧视频节点溢出视口
  useEffect(() => {
    if (!canvas || canvas.nodes.length === 0) return;
    if (fittedCanvasIdRef.current === canvas.id) return;
    fittedCanvasIdRef.current = canvas.id;
    // 延时等待一次渲染，让节点实际高度被 ResizeObserver 写入后再 fit
    const t = setTimeout(() => {
      fitContent();
    }, 100);
    return () => clearTimeout(t);
  }, [canvas?.id, canvas?.nodes.length, fitContent]);

  const addNodeAtMenu = useCallback((nodeType: string) => {
    if (!contextMenu || !canvasRef.current) return;
    const rect = canvasRef.current.getBoundingClientRect();
    const cx = (contextMenu.x - rect.left - offsetRef.current.x) / scaleRef.current - NODE_DEFAULT_WIDTH / 2;
    const cy = (contextMenu.y - rect.top - offsetRef.current.y) / scaleRef.current - NODE_DEFAULT_HEIGHT / 2;
    addNode(nodeType, cx, cy);
    setContextMenu(null);
  }, [contextMenu, addNode]);

  const handleCanvasMouseMove = useCallback((e: MouseEvent) => {
    if (isPanning.current) {
      offsetRef.current = {
        x: panStart.current.ox + (e.clientX - panStart.current.x),
        y: panStart.current.oy + (e.clientY - panStart.current.y),
      };
      applyTransform();
    }
    const cf = connectingFromRef.current;
    if (cf) {
      const cv = canvasDataRef.current;
      const rect = canvasRef.current?.getBoundingClientRect();
      if (!cv || !rect) return;
      const fromNode = cv.nodes.find((n) => n.id === cf);
      if (!fromNode) return;
      const fc = getNodeCenter(fromNode);
      const s = scaleRef.current;
      const o = offsetRef.current;
      setDragLine({
        fromX: fc.x * s + o.x + (fromNode.width / 2) * s,
        fromY: fc.y * s + o.y,
        toX: e.clientX - rect.left,
        toY: e.clientY - rect.top,
      });
    }
  }, [applyTransform]);

  const handleCanvasMouseUp = useCallback(() => {
    if (isPanning.current) {
      isPanning.current = false;
      setPanCursor('grab');
      // sync state once after panning so dependent renders (popup, zoom %) catch up
      setOffset({ ...offsetRef.current });
    }
    if (connectingFromRef.current) {
      setConnectingFrom(null);
      setDragLine(null);
    }
  }, [setConnectingFrom]);

  useEffect(() => {
    window.addEventListener('mousemove', handleCanvasMouseMove);
    window.addEventListener('mouseup', handleCanvasMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleCanvasMouseMove);
      window.removeEventListener('mouseup', handleCanvasMouseUp);
    };
  }, [handleCanvasMouseMove, handleCanvasMouseUp]);

  // Delete/Backspace 键删除选中边（避免在输入框内触发）
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key !== 'Delete' && e.key !== 'Backspace') return;
      const target = e.target as HTMLElement;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) return;
      if (!selectedEdgeId) return;
      e.preventDefault();
      deleteEdge(selectedEdgeId);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [selectedEdgeId, deleteEdge]);

  // 全局粘贴监听：当焦点不在输入框时，将剪贴板内容粘贴到画布
  useEffect(() => {
    const handler = async (e: ClipboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) return;
      if (!canvas) return;
      const items = Array.from(e.clipboardData?.items || []);
      let handled = false;
      for (const item of items) {
        if (item.kind === 'file' && item.type.startsWith('image/')) {
          const file = item.getAsFile();
          if (file) {
            handled = true;
            await createImageNodeFromFile(file);
          }
        } else if (item.kind === 'string') {
          handled = true;
          const text = await new Promise<string>((resolve) => item.getAsString(resolve));
          if (text.trim()) {
            await createScriptNodeFromText(text);
          }
        }
      }
      if (handled) {
        e.preventDefault();
      }
    };
    window.addEventListener('paste', handler);
    return () => window.removeEventListener('paste', handler);
  }, [canvas, createImageNodeFromFile, createScriptNodeFromText]);

  // wheel zoom centered on the mouse cursor, only when Ctrl is held
  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const handler = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const delta = e.deltaY > 0 ? 0.9 : 1.1;
      const rect = el.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      const s = scaleRef.current;
      const o = offsetRef.current;
      const canvasX = (mouseX - o.x) / s;
      const canvasY = (mouseY - o.y) / s;
      const newScale = Math.max(0.1, Math.min(3, s * delta));
      offsetRef.current = { x: mouseX - canvasX * newScale, y: mouseY - canvasY * newScale };
      scaleRef.current = newScale;
      applyTransform();
      setScale(newScale);
      setOffset({ ...offsetRef.current });
    };
    el.addEventListener('wheel', handler, { passive: false });
    return () => el.removeEventListener('wheel', handler);
  }, [applyTransform]);

  const zoomBy = useCallback((delta: number) => {
    const newScale = Math.max(0.1, Math.min(3, scaleRef.current + delta));
    scaleRef.current = newScale;
    applyTransform();
    setScale(newScale);
  }, [applyTransform]);

  // stable per-node callbacks (cached by node id) so NodeCard memo stays effective
  const cbCache = useRef(new Map<string, {
    onSelect: () => void;
    onStartConnect: () => void;
    onEndConnect: () => void;
    onGenerate: () => void;
    onPositionChange: (x: number, y: number) => void;
    onHeightChange: (id: string, height: number) => void;
  }>());

  const getNodeCallbacks = useCallback((node: CanvasNode) => {
    let cbs = cbCache.current.get(node.id);
    if (!cbs) {
      cbs = {
        onSelect: () => setSelectedNode(node.id),
        onStartConnect: () => {
          setConnectingFrom(node.id);
          // 完全从最新画布数据查找节点，避免闭包捕获旧 node 坐标
          const cv = canvasDataRef.current;
          const n = cv?.nodes.find((x) => x.id === node.id);
          if (!n) return;
          const c = getNodeCenter(n);
          const s = scaleRef.current;
          const o = offsetRef.current;
          const sx = c.x * s + o.x + (n.width / 2) * s;
          const sy = c.y * s + o.y;
          setDragLine({ fromX: sx, fromY: sy, toX: sx, toY: sy });
        },
        onEndConnect: () => {
          const cf = connectingFromRef.current;
          if (cf) addEdge(cf, node.id);
        },
        onGenerate: () => triggerGenerate(node.id),
        onPositionChange: (x: number, y: number) => handlePositionChange(node.id, x, y),
        onHeightChange: handleNodeHeightChange,
      };
      cbCache.current.set(node.id, cbs);
    }
    return cbs;
  }, [setSelectedNode, setConnectingFrom, addEdge, triggerGenerate, handlePositionChange, handleNodeHeightChange]);

  const nodeMap = useMemo(() => new Map((canvas?.nodes ?? []).map((n) => [n.id, n])), [canvas]);

  if (!canvas) {
    return (
      <div className="flex-1 flex items-center justify-center canvas-grid">
        <div className="text-center glass rounded-3xl px-10 py-8 shadow-soft-lg">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-teal-600 to-emerald-700 flex items-center justify-center mb-4 shadow-glow">
            <Feather size={32} className="text-theme-invert" />
          </div>
          <p className="text-lg mb-2 text-theme-main font-semibold">打开或创建一个画布开始创作</p>
          <p className="text-sm text-theme-sub mb-6">点击左上角按钮选择画布，或使用 AI 智能体一键生成短剧</p>
          {onOpenAgent && (
            <button
              className="btn-primary px-6 py-3 text-base shadow-lg shadow-accent/30 animate-pulse-glow"
              onClick={onOpenAgent}
            >
              <Bot size={20} />
              <span>AI 短剧创作助手</span>
              <Sparkles size={16} className="text-white/80" />
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div
      ref={canvasRef}
      className="flex-1 relative overflow-hidden canvas-grid canvas-bg"
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onMouseDown={handleCanvasMouseDown}
      onContextMenu={handleContextMenu}
      style={{ cursor: panCursor }}
    >
      <div
        ref={transformRef}
        className="absolute inset-0"
        style={{ transformOrigin: '0 0' }}
      >
        <svg
          className="absolute top-0 left-0 pointer-events-none"
          style={{ width: 10000, height: 10000, overflow: 'visible' }}
        >
          <defs>
            <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
              <polygon points="0 0, 8 3, 0 6" fill="var(--color-accent)" />
            </marker>
            <marker id="arrowhead-dim" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
              <polygon points="0 0, 8 3, 0 6" fill="var(--color-text-sub)" />
            </marker>
          </defs>
          {canvas.edges.map((edge) => {
            const src = nodeMap.get(edge.source_node_id);
            const tgt = nodeMap.get(edge.target_node_id);
            if (!src || !tgt) return null;
            const isSelected = selectedEdgeId === edge.id;
            // 用实际渲染高度（由 NodeCard ResizeObserver 回写）替代数据库 height 字段
            const srcActualHeight = nodeHeightsRef.current.get(src.id) ?? src.height;
            const tgtActualHeight = nodeHeightsRef.current.get(tgt.id) ?? tgt.height;
            const srcWithH = { ...src, height: srcActualHeight };
            const tgtWithH = { ...tgt, height: tgtActualHeight };
            // 动态选择起点/终点边，避免连线穿过节点本身
            const { sx, sy, tx, ty } = getEdgeEndpoints(srcWithH, tgtWithH);
            const processing = src.status === 'processing' || tgt.status === 'processing';
            // 中点用于显示 label 和删除按钮
            const midX = (sx + tx) / 2;
            const midY = (sy + ty) / 2;
            const labelText = edge.label || (
              edge.edge_type === 'sequence' ? '顺序' :
              edge.edge_type === 'reference' ? '引用' :
              edge.edge_type === 'association' ? '关联' : ''
            );
            const labelW = Math.max(28, labelText.length * 12 + 8);
            return (
              <g
                key={edge.id}
                className="pointer-events-auto cursor-pointer"
                onClick={(e) => { e.stopPropagation(); setSelectedEdge(edge.id); }}
                onContextMenu={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setSelectedEdge(edge.id);
                  setEdgeContextMenu({ x: e.clientX, y: e.clientY, edgeId: edge.id });
                }}
                style={{ zIndex: isSelected ? 30 : 10 }}
              >
                {/* 透明加粗命中区 */}
                <path d={bezierPath(sx, sy, tx, ty)} stroke="transparent" strokeWidth={16} fill="none" />
                <path
                  d={bezierPath(sx, sy, tx, ty)}
                  stroke={isSelected ? 'var(--color-accent)' : 'var(--color-text-sub)'}
                  strokeWidth={isSelected ? 2.5 : 1.5}
                  fill="none"
                  className={processing ? 'edge-flow' : ''}
                  markerEnd={isSelected ? 'url(#arrowhead)' : 'url(#arrowhead-dim)'}
                />
                {/* label 标签 */}
                {labelText && (
                  <g>
                    <rect
                      x={midX - labelW / 2}
                      y={midY - 9}
                      width={labelW}
                      height={18}
                      rx={9}
                      fill={isSelected ? 'var(--color-accent)' : 'var(--color-panel-bg)'}
                      stroke={isSelected ? 'var(--color-accent-glow)' : 'var(--color-panel-border)'}
                      strokeWidth={1}
                    />
                    <text
                      x={midX}
                      y={midY + 3}
                      textAnchor="middle"
                      fontSize={10}
                      fill={isSelected ? 'var(--color-text-invert)' : 'var(--color-text-sub)'}
                      style={{ pointerEvents: 'none', userSelect: 'none' }}
                    >
                      {labelText}
                    </text>
                  </g>
                )}
                {/* 选中时显示删除按钮 */}
                {isSelected && (
                  <g
                    className="cursor-pointer"
                    onClick={(e) => { e.stopPropagation(); deleteEdge(edge.id); }}
                  >
                    <circle
                      cx={midX + labelW / 2 + 6}
                      cy={midY}
                      r={9}
                      fill="#ef4444"
                      stroke="#fff"
                      strokeWidth={1}
                    />
                    <path
                      d={`M ${midX + labelW / 2 + 6 - 3} ${midY - 3} L ${midX + labelW / 2 + 6 + 3} ${midY + 3} M ${midX + labelW / 2 + 6 + 3} ${midY - 3} L ${midX + labelW / 2 + 6 - 3} ${midY + 3}`}
                      stroke="#fff"
                      strokeWidth={1.5}
                      strokeLinecap="round"
                    />
                  </g>
                )}
              </g>
            );
          })}
          {dragLine && (
            <path
              d={bezierPath(dragLine.fromX / scale - offset.x / scale, dragLine.fromY / scale - offset.y / scale, dragLine.toX / scale - offset.x / scale, dragLine.toY / scale - offset.y / scale)}
              stroke="var(--color-accent)"
              strokeWidth={2}
              fill="none"
              strokeDasharray="6 3"
            />
          )}
        </svg>

        {canvas.nodes.map((node) => {
          const cbs = getNodeCallbacks(node);
          return (
            <NodeCard
              key={node.id}
              node={node}
              isSelected={selectedNodeId === node.id}
              scale={scale}
              gridMode={selectedNodeId === node.id ? gridMode : 'none'}
              onSelect={cbs.onSelect}
              onStartConnect={cbs.onStartConnect}
              onEndConnect={cbs.onEndConnect}
              onPositionChange={cbs.onPositionChange}
              onGenerate={cbs.onGenerate}
              onHeightChange={cbs.onHeightChange}
            />
          );
        })}
      </div>

      {/* 完整属性面板 — 选中节点即显示，固定在节点下方 */}
      {selectedNodeId && showPropertyPopup && (() => {
        const node = canvas.nodes.find((n) => n.id === selectedNodeId);
        if (!node) return null;
        const nodeActualHeight = nodeHeightsRef.current.get(node.id) ?? node.height ?? 160;
        return (
          <NodePropertyPopup
            node={node}
            screenX={node.x * scale + offset.x}
            screenY={node.y * scale + offset.y}
            nodeWidth={node.width * scale}
            nodeHeight={nodeActualHeight * scale}
            scale={scale}
            onClose={() => { setShowPropertyPopup(false); setQuickReferenceNodeId(null); }}
            autoOpenAssetPicker={quickReferenceNodeId === node.id}
          />
        );
      })()}

      {/* 局部重绘 MaskEditor */}
      {maskEditorNodeId && (() => {
        const node = canvas.nodes.find((n) => n.id === maskEditorNodeId);
        if (!node || !node.result_url) return null;
        return (
          <MaskEditor
            imageUrl={node.result_url}
            onConfirm={async (maskDataUrl, inpaintPrompt) => {
              const cfg = (node.config as NodeConfig | undefined) || {};
              updateNodeData(node.id, {
                prompt: inpaintPrompt,
                config: { ...cfg, mask_data_url: maskDataUrl, previous_result_url: node.result_url } as Record<string, unknown>,
              });
              setMaskEditorNodeId(null);
              triggerGenerate(node.id);
            }}
            onCancel={() => setMaskEditorNodeId(null)}
          />
        );
      })()}

      {/* 运镜/影视参数面板 */}
      {cinematicNodeId && (() => {
        const node = canvas.nodes.find((n) => n.id === cinematicNodeId);
        if (!node) return null;
        return (
          <CinematicQuickPanel
            node={node}
            onConfirm={(cinematicConfig) => {
              const cfg = (node.config as NodeConfig | undefined) || {};
              updateNodeData(node.id, {
                config: { ...cfg, ...cinematicConfig } as Record<string, unknown>,
              });
              setCinematicNodeId(null);
            }}
            onClose={() => setCinematicNodeId(null)}
          />
        );
      })()}

      {pasting && (
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50 glass rounded-2xl px-4 py-3 flex items-center gap-2 text-sm text-theme-main shadow-soft-lg">
          <Loader2 size={16} className="animate-spin text-accent" />
          正在粘贴并上传资产…
        </div>
      )}

      <div className="absolute bottom-6 left-6 flex items-center gap-2 glass rounded-2xl px-4 py-2 text-xs text-theme-sub shadow-soft">
        <button className="btn-ghost px-2 py-0.5 text-xs" onClick={() => zoomBy(-0.1)}>−</button>
        <span className="w-10 text-center">{Math.round(scale * 100)}%</span>
        <button className="btn-ghost px-2 py-0.5 text-xs" onClick={() => zoomBy(0.1)}>+</button>
        <span className="mx-1 text-panel-border">|</span>
        <button className="btn-ghost px-2 py-0.5 text-xs flex items-center gap-1" onClick={fitContent} title="适合内容">
          <Maximize size={11} />
        </button>
        <button className="btn-ghost px-2 py-0.5 text-xs flex items-center gap-1" onClick={resetView} title="重置视图">
          <Focus size={11} />
        </button>
        <span className="mx-1 text-panel-border">|</span>
        <span>节点: {canvas.nodes.length}</span>
        <span>连线: {canvas.edges.length}</span>
      </div>

      {/* 快捷上传隐藏 file input */}
      <input ref={quickUploadRef} type="file" className="hidden" onChange={handleQuickUploadChange} />

      {contextMenu && (
        <div
          className="fixed z-[200] glass rounded-2xl shadow-soft-lg py-1.5 min-w-[180px] border border-panel-border/50"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="px-3 py-1 text-[10px] text-theme-hint font-semibold uppercase tracking-wider">画布操作</div>
          <button className="w-full px-3 py-2 text-left text-xs text-theme-main hover:bg-accent/10 flex items-center gap-2 transition-colors" onClick={() => { resetView(); setContextMenu(null); }}>
            <Focus size={13} className="text-accent" /> 重置视图
          </button>
          <button className="w-full px-3 py-2 text-left text-xs text-theme-main hover:bg-accent/10 flex items-center gap-2 transition-colors" onClick={() => { fitContent(); setContextMenu(null); }}>
            <Maximize size={13} className="text-accent" /> 适合内容
          </button>
          <div className="my-1 border-t border-panel-border/30" />
          <div className="px-3 py-1 text-[10px] text-theme-hint font-semibold uppercase tracking-wider">添加节点</div>
          {[
            { type: 'script', label: '剧本', icon: <FileText size={13} className="text-amber-400" /> },
            { type: 'character', label: '角色', icon: <User size={13} className="text-pink-400" /> },
            { type: 'scene', label: '场景', icon: <MapPin size={13} className="text-green-400" /> },
            { type: 'storyboard', label: '分镜', icon: <Clapperboard size={13} className="text-theme-sub" /> },
            { type: 'image', label: '图片', icon: <ImageIcon size={13} className="text-blue-400" /> },
            { type: 'video', label: '视频', icon: <Film size={13} className="text-red-400" /> },
            { type: 'audio', label: '音频', icon: <Volume2 size={13} className="text-cyan-400" /> },
          ].map((item) => (
            <button
              key={item.type}
              className="w-full px-3 py-2 text-left text-xs text-theme-main hover:bg-accent/10 flex items-center gap-2 transition-colors"
              onClick={() => addNodeAtMenu(item.type)}
            >
              {item.icon} {item.label}节点
            </button>
          ))}
        </div>
      )}

      {edgeContextMenu && (
        <div
          className="fixed z-[200] glass rounded-2xl shadow-soft-lg py-1.5 min-w-[160px] border border-panel-border/50"
          style={{ left: edgeContextMenu.x, top: edgeContextMenu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="px-3 py-1 text-[10px] text-theme-hint font-semibold uppercase tracking-wider">连线类型</div>
          {([
            { type: 'default', label: '默认', desc: '普通连线' },
            { type: 'reference', label: '引用', desc: '角色/场景作用于分镜' },
            { type: 'sequence', label: '顺序', desc: '分镜先后顺序' },
            { type: 'association', label: '关联', desc: '一般关联' },
          ] as const).map((item) => {
            const edge = canvas.edges.find((e) => e.id === edgeContextMenu.edgeId);
            const isActive = edge?.edge_type === item.type;
            return (
              <button
                key={item.type}
                className={`w-full px-3 py-2 text-left text-xs transition-colors flex items-center justify-between gap-2 ${
                  isActive ? 'text-accent bg-accent/10' : 'text-theme-main hover:bg-accent/10'
                }`}
                onClick={() => {
                  updateEdgeType(edgeContextMenu.edgeId, item.type);
                  setEdgeContextMenu(null);
                }}
              >
                <span>{item.label}</span>
                <span className="text-[10px] text-theme-hint">{item.desc}</span>
              </button>
            );
          })}
          <div className="my-1 border-t border-panel-border/30" />
          <button
            className="w-full px-3 py-2 text-left text-xs text-red-400 hover:bg-red-500/10 flex items-center gap-2 transition-colors"
            onClick={() => {
              deleteEdge(edgeContextMenu.edgeId);
              setEdgeContextMenu(null);
            }}
          >
            删除连线
          </button>
        </div>
      )}
    </div>
  );
}
