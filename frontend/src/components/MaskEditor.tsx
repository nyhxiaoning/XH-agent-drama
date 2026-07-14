import { useCallback, useEffect, useRef, useState } from "react";
import { Brush, Eraser, Trash2, X, Check, Eye, EyeOff } from "lucide-react";

export interface MaskEditorProps {
  imageUrl: string;
  onConfirm: (maskDataUrl: string, prompt: string) => void;
  onCancel: () => void;
}

type Tool = "brush" | "eraser";

const BRUSH_SIZES = [10, 30, 60, 100];
const MAX_CANVAS_DIM = 1024;
const MIN_COVERAGE = 0.02; // 最小 2% 涂抹面积

export function MaskEditor({ imageUrl, onConfirm, onCancel }: MaskEditorProps) {
  const imageRef = useRef<HTMLImageElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const drawingRef = useRef(false);
  const lastPointRef = useRef<{ x: number; y: number } | null>(null);
  const [tool, setTool] = useState<Tool>("brush");
  const [brushSize, setBrushSize] = useState(30);
  const [prompt, setPrompt] = useState("");
  const [showMaskOverlay, setShowMaskOverlay] = useState(true);
  const [imageLoaded, setImageLoaded] = useState(false);
  const [imageSize, setImageSize] = useState<{ w: number; h: number }>({ w: 0, h: 0 });
  const [coverage, setCoverage] = useState(0);

  // 初始化 canvas 尺寸
  const handleImageLoad = useCallback(() => {
    const img = imageRef.current;
    if (!img) return;
    const naturalW = img.naturalWidth;
    const naturalH = img.naturalHeight;
    // 限制最大尺寸
    const scale = Math.min(1, MAX_CANVAS_DIM / Math.max(naturalW, naturalH));
    const w = Math.round(naturalW * scale);
    const h = Math.round(naturalH * scale);
    setImageSize({ w, h });

    const canvas = canvasRef.current;
    if (canvas) {
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext("2d");
      if (ctx) {
        ctx.clearRect(0, 0, w, h);
      }
    }
    setImageLoaded(true);
  }, []);

  // 获取 canvas 坐标
  const getCanvasPoint = useCallback((clientX: number, clientY: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    return {
      x: (clientX - rect.left) * scaleX,
      y: (clientY - rect.top) * scaleY,
    };
  }, []);

  // 绘制
  const drawAt = useCallback(
    (x: number, y: number) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      const radius = brushSize / 2;

      if (tool === "brush") {
        ctx.globalCompositeOperation = "source-over";
        ctx.fillStyle = "rgba(255, 0, 128, 0.55)";
      } else {
        ctx.globalCompositeOperation = "destination-out";
        ctx.fillStyle = "rgba(0, 0, 0, 1)";
      }

      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fill();

      // 连线绘制（拖动时）
      const last = lastPointRef.current;
      if (last) {
        ctx.lineWidth = brushSize;
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        if (tool === "brush") {
          ctx.strokeStyle = "rgba(255, 0, 128, 0.55)";
        } else {
          ctx.strokeStyle = "rgba(0, 0, 0, 1)";
        }
        ctx.beginPath();
        ctx.moveTo(last.x, last.y);
        ctx.lineTo(x, y);
        ctx.stroke();
      }
      lastPointRef.current = { x, y };
    },
    [brushSize, tool]
  );

  const handlePointerDown = useCallback(
    (e: React.PointerEvent) => {
      e.preventDefault();
      e.stopPropagation();
      drawingRef.current = true;
      lastPointRef.current = null;
      const pt = getCanvasPoint(e.clientX, e.clientY);
      if (pt) drawAt(pt.x, pt.y);
    },
    [drawAt, getCanvasPoint]
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!drawingRef.current) return;
      e.preventDefault();
      const pt = getCanvasPoint(e.clientX, e.clientY);
      if (pt) drawAt(pt.x, pt.y);
    },
    [drawAt, getCanvasPoint]
  );

  const handlePointerUp = useCallback(() => {
    drawingRef.current = false;
    lastPointRef.current = null;
    // 更新覆盖率
    updateCoverage();
  }, []);

  // 计算涂抹覆盖率
  const updateCoverage = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const pixels = imageData.data;
    let painted = 0;
    const total = pixels.length / 4;
    for (let i = 3; i < pixels.length; i += 4) {
      if (pixels[i] > 10) painted++;
    }
    setCoverage(painted / total);
  }, []);

  // 清空
  const handleClear = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    setCoverage(0);
  }, []);

  // 生成 mask PNG data URL
  // 规范：白色 (#FFFFFF) = 重绘区，黑色 (#000000) = 保留区
  const generateMaskDataUrl = useCallback((): string => {
    const canvas = canvasRef.current;
    if (!canvas) return "";
    const w = canvas.width;
    const h = canvas.height;

    // 创建临时 canvas 生成黑白 mask
    const tempCanvas = document.createElement("canvas");
    tempCanvas.width = w;
    tempCanvas.height = h;
    const tempCtx = tempCanvas.getContext("2d");
    if (!tempCtx) return "";

    // 填充黑色背景（保留区）
    tempCtx.fillStyle = "#000000";
    tempCtx.fillRect(0, 0, w, h);

    // 读取原 canvas 的 alpha 通道，alpha > 0 的区域设为白色（重绘区）
    const sourceCtx = canvas.getContext("2d");
    if (!sourceCtx) return "";
    const sourceData = sourceCtx.getImageData(0, 0, w, h);
    const sourcePixels = sourceData.data;

    const destImageData = tempCtx.getImageData(0, 0, w, h);
    const destPixels = destImageData.data;

    for (let i = 0; i < sourcePixels.length; i += 4) {
      if (sourcePixels[i + 3] > 10) {
        // 有涂抹的区域 → 白色
        destPixels[i] = 255;
        destPixels[i + 1] = 255;
        destPixels[i + 2] = 255;
        destPixels[i + 3] = 255;
      }
    }
    tempCtx.putImageData(destImageData, 0, 0);

    return tempCanvas.toDataURL("image/png");
  }, []);

  const handleConfirm = useCallback(() => {
    if (coverage < MIN_COVERAGE) {
      return;
    }
    const maskDataUrl = generateMaskDataUrl();
    if (!maskDataUrl) return;
    onConfirm(maskDataUrl, prompt);
  }, [coverage, generateMaskDataUrl, onConfirm, prompt]);

  // ESC 关闭
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onCancel]);

  const coveragePercent = (coverage * 100).toFixed(1);
  const hasEnoughCoverage = coverage >= MIN_COVERAGE;

  return (
    <div className="fixed inset-0 z-[200] bg-black/80 backdrop-blur-sm flex items-center justify-center no-pan" onClick={onCancel}>
      <div
        className="relative bg-[#1a1a2e] rounded-2xl shadow-2xl border border-white/10 w-[90vw] max-w-[1000px] max-h-[90vh] flex flex-col overflow-hidden no-pan"
        onClick={(e) => e.stopPropagation()}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-white/10">
          <div className="flex items-center gap-2 text-white">
            <Brush size={20} className="text-pink-400" />
            <h2 className="text-base font-semibold">局部重绘 — 涂抹要修改的区域</h2>
          </div>
          <button
            className="text-white/60 hover:text-white p-1 rounded-lg hover:bg-white/10 transition-colors"
            onClick={onCancel}
          >
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 flex overflow-hidden">
          {/* Canvas area */}
          <div className="flex-1 flex items-center justify-center p-4 bg-[#0d0d1a] overflow-auto" ref={containerRef}>
            <div className="relative inline-block">
              <img
                ref={imageRef}
                src={imageUrl}
                alt="原图"
                className="block max-w-full max-h-[65vh] select-none"
                draggable={false}
                onLoad={handleImageLoad}
                style={{ display: imageLoaded ? "block" : "none" }}
              />
              {imageLoaded && (
                <canvas
                  ref={canvasRef}
                  className="absolute inset-0 cursor-crosshair"
                  style={{
                    width: "100%",
                    height: "100%",
                    opacity: showMaskOverlay ? 1 : 0,
                  }}
                  onPointerDown={handlePointerDown}
                  onPointerMove={handlePointerMove}
                  onPointerUp={handlePointerUp}
                  onPointerLeave={handlePointerUp}
                />
              )}
              {!imageLoaded && (
                <div className="flex items-center justify-center w-[400px] h-[300px] text-white/40">
                  加载图片中...
                </div>
              )}
            </div>
          </div>

          {/* Sidebar */}
          <div className="w-[280px] border-l border-white/10 bg-[#1a1a2e] p-4 flex flex-col gap-4 overflow-y-auto">
            {/* 工具选择 */}
            <div>
              <label className="text-xs font-semibold text-white/60 uppercase tracking-wide mb-2 block">工具</label>
              <div className="flex gap-2">
                <button
                  className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-sm font-medium transition-colors ${
                    tool === "brush"
                      ? "bg-pink-500/30 text-pink-300 border border-pink-500/50"
                      : "bg-white/5 text-white/50 border border-white/10 hover:bg-white/10"
                  }`}
                  onClick={() => setTool("brush")}
                >
                  <Brush size={16} /> 画笔
                </button>
                <button
                  className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-sm font-medium transition-colors ${
                    tool === "eraser"
                      ? "bg-pink-500/30 text-pink-300 border border-pink-500/50"
                      : "bg-white/5 text-white/50 border border-white/10 hover:bg-white/10"
                  }`}
                  onClick={() => setTool("eraser")}
                >
                  <Eraser size={16} /> 橡皮
                </button>
              </div>
            </div>

            {/* 画笔大小 */}
            <div>
              <label className="text-xs font-semibold text-white/60 uppercase tracking-wide mb-2 block">
                画笔大小
              </label>
              <div className="flex gap-2">
                {BRUSH_SIZES.map((size) => (
                  <button
                    key={size}
                    className={`flex-1 py-2 rounded-lg text-xs font-medium transition-colors ${
                      brushSize === size
                        ? "bg-pink-500/30 text-pink-300 border border-pink-500/50"
                        : "bg-white/5 text-white/50 border border-white/10 hover:bg-white/10"
                    }`}
                    onClick={() => setBrushSize(size)}
                  >
                    {size}px
                  </button>
                ))}
              </div>
            </div>

            {/* 操作按钮 */}
            <div className="flex gap-2">
              <button
                className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-sm bg-white/5 text-white/70 border border-white/10 hover:bg-white/10 transition-colors"
                onClick={handleClear}
              >
                <Trash2 size={15} /> 清空
              </button>
              <button
                className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-sm bg-white/5 text-white/70 border border-white/10 hover:bg-white/10 transition-colors"
                onClick={() => setShowMaskOverlay((v) => !v)}
              >
                {showMaskOverlay ? <EyeOff size={15} /> : <Eye size={15} />}
                {showMaskOverlay ? "隐藏蒙版" : "显示蒙版"}
              </button>
            </div>

            {/* 覆盖率 */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-xs font-semibold text-white/60 uppercase tracking-wide">涂抹覆盖率</label>
                <span className={`text-xs font-bold ${hasEnoughCoverage ? "text-green-400" : "text-yellow-400"}`}>
                  {coveragePercent}%
                </span>
              </div>
              <div className="h-2 rounded-full bg-white/10 overflow-hidden">
                <div
                  className={`h-full transition-all ${hasEnoughCoverage ? "bg-green-500" : "bg-yellow-500"}`}
                  style={{ width: `${Math.min(coverage * 100 * 5, 100)}%` }}
                />
              </div>
              {!hasEnoughCoverage && (
                <p className="text-xs text-yellow-400/70 mt-1">至少涂抹 2% 的画面面积</p>
              )}
            </div>

            {/* 重绘描述 */}
            <div className="flex-1 flex flex-col">
              <label className="text-xs font-semibold text-white/60 uppercase tracking-wide mb-2">
                重绘描述（自然语言）
              </label>
              <textarea
                className="flex-1 min-h-[100px] w-full rounded-lg bg-white/5 border border-white/10 text-white/90 text-sm p-3 resize-none focus:outline-none focus:border-pink-500/50 placeholder:text-white/30"
                placeholder="例如：把背景换成夕阳下的海边，保持人物不变"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
              />
            </div>

            {/* 确认/取消 */}
            <div className="flex gap-2">
              <button
                className="flex-1 py-2.5 rounded-lg text-sm font-medium bg-white/5 text-white/60 border border-white/10 hover:bg-white/10 transition-colors"
                onClick={onCancel}
              >
                取消
              </button>
              <button
                className={`flex-1 flex items-center justify-center gap-1.5 py-2.5 rounded-lg text-sm font-semibold transition-colors ${
                  hasEnoughCoverage && prompt.trim()
                    ? "bg-gradient-to-r from-pink-600 to-fuchsia-600 text-white hover:from-pink-500 hover:to-fuchsia-500"
                    : "bg-white/5 text-white/30 cursor-not-allowed"
                }`}
                disabled={!hasEnoughCoverage || !prompt.trim()}
                onClick={handleConfirm}
              >
                <Check size={16} /> 生成
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
