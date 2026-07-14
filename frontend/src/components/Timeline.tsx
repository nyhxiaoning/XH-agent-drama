import { useState, useMemo, useEffect, useRef } from 'react';
import { Play, Pause, SkipForward, SkipBack, X, ChevronDown, ChevronUp, Clock, Film, Clapperboard } from 'lucide-react';
import { useEditorStore } from '@/store/editor';
import type { CanvasNode } from '@/types';

interface TimelineItem {
  id: string;
  title: string;
  nodeType: string;
  url: string | undefined;
  thumbnail: string | undefined;
  duration: number;
  isVideo: boolean;
}

export function Timeline() {
  const canvas = useEditorStore((s) => s.canvas);
  const [collapsed, setCollapsed] = useState(false);
  const [showPlayer, setShowPlayer] = useState(false);

  const items = useMemo<TimelineItem[]>(() => {
    if (!canvas) return [];
    const sbNodes = canvas.nodes.filter(
      (n) =>
        (n.node_type === 'storyboard' || n.node_type === 'video') &&
        n.status === 'success' &&
        n.result_url
    );
    if (sbNodes.length === 0) return [];
    const byId = new Map(sbNodes.map((n) => [n.id, n]));
    const visited = new Set<string>();
    const sorted: CanvasNode[] = [];
    const visit = (n: CanvasNode) => {
      if (visited.has(n.id)) return;
      visited.add(n.id);
      const cfg = (n.config || {}) as Record<string, unknown>;
      const prevId = cfg.prev_storyboard_id as string | undefined;
      if (prevId && byId.has(prevId)) {
        visit(byId.get(prevId)!);
      }
      sorted.push(n);
    };
    sbNodes.forEach(visit);
    return sorted.map((n) => {
      const cfg = (n.config || {}) as Record<string, unknown>;
      return {
        id: n.id,
        title: n.title,
        nodeType: n.node_type,
        url: n.result_url,
        thumbnail: n.thumbnail_url || n.result_url,
        duration: (cfg.duration_seconds as number) || (n.node_type === 'video' ? 5 : 3),
        isVideo: n.node_type === 'video',
      };
    });
  }, [canvas]);

  if (!canvas || items.length === 0) return null;

  return (
    <>
      <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-50 glass rounded-2xl shadow-soft-lg border border-panel-border/50 max-w-[80vw]">
        <div className="flex items-center gap-2 px-3 py-2">
          <button
            className="btn-ghost px-2.5 py-1 text-xs flex items-center gap-1.5"
            onClick={() => setShowPlayer(true)}
            title="顺序预览"
          >
            <Play size={13} className="text-accent" />
            <span>预览</span>
          </button>
          <span className="text-[10px] text-theme-hint uppercase tracking-wider">
            {items.length} 个分镜
          </span>
          <div className="flex-1 overflow-hidden mx-2">
            <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar py-0.5">
              {items.map((item, idx) => (
                <div
                  key={item.id}
                  className="relative flex-shrink-0 group cursor-pointer"
                  onClick={() => setShowPlayer(true)}
                >
                  <div className="w-12 h-9 rounded-md overflow-hidden bg-panel-border/20 border border-panel-border/40">
                    {item.thumbnail ? (
                      <img src={item.thumbnail} alt={item.title} className="w-full h-full object-cover" />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center">
                        <Clapperboard size={14} className="text-theme-hint" />
                      </div>
                    )}
                  </div>
                  <span className="absolute -top-1 -left-1 text-[9px] bg-panel-bg rounded px-1 text-theme-hint">
                    {idx + 1}
                  </span>
                </div>
              ))}
            </div>
          </div>
          <button
            className="btn-ghost px-1.5 py-1 text-xs"
            onClick={() => setCollapsed((v) => !v)}
            title={collapsed ? '展开' : '收起'}
          >
            {collapsed ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          </button>
        </div>
        {!collapsed && (
          <div className="px-3 pb-2 pt-0.5 border-t border-panel-border/30">
            <div className="flex items-center gap-3 text-[10px] text-theme-hint">
              <span className="flex items-center gap-1">
                <Clock size={10} />
                总时长 {items.reduce((a, b) => a + b.duration, 0)}s
              </span>
              <span className="flex items-center gap-1">
                <Film size={10} />
                {items.filter((i) => i.isVideo).length} 视频 / {items.filter((i) => !i.isVideo).length} 图
              </span>
            </div>
          </div>
        )}
      </div>

      {showPlayer && (
        <TimelinePlayer items={items} onClose={() => setShowPlayer(false)} />
      )}
    </>
  );
}

function TimelinePlayer({ items, onClose }: { items: TimelineItem[]; onClose: () => void }) {
  const [currentIdx, setCurrentIdx] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [progress, setProgress] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  const current = items[currentIdx];

  useEffect(() => {
    if (!playing || !current) return;
    setProgress(0);
    if (current.isVideo) {
      const v = videoRef.current;
      if (v) {
        v.currentTime = 0;
        v.play().catch(() => setPlaying(false));
      }
      return;
    }
    const step = 100 / (current.duration * 10);
    timerRef.current = setInterval(() => {
      setProgress((p) => {
        const np = p + step;
        if (np >= 100) {
          goNext();
          return 0;
        }
        return np;
      });
    }, 100);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [playing, currentIdx, current]);

  const goNext = () => {
    setProgress(0);
    setCurrentIdx((i) => {
      if (i + 1 >= items.length) {
        setPlaying(false);
        return i;
      }
      return i + 1;
    });
  };

  const goPrev = () => {
    setProgress(0);
    setCurrentIdx((i) => Math.max(0, i - 1));
  };

  const togglePlay = () => {
    if (currentIdx >= items.length - 1 && progress >= 100) {
      setCurrentIdx(0);
      setProgress(0);
      setPlaying(true);
      return;
    }
    setPlaying((v) => !v);
  };

  const handleVideoEnded = () => goNext();

  if (!current) return null;

  return (
    <div className="fixed inset-0 z-[300] bg-black/85 backdrop-blur-sm flex flex-col items-center justify-center" onClick={onClose}>
      <div className="absolute top-4 right-4">
        <button className="text-white/70 hover:text-white p-2" onClick={onClose}>
          <X size={24} />
        </button>
      </div>
      <div className="absolute top-4 left-4 text-white/60 text-sm">
        {currentIdx + 1} / {items.length} — {current.title}
      </div>

      <div className="flex-1 flex items-center justify-center max-w-[90vw] max-h-[75vh]" onClick={(e) => e.stopPropagation()}>
        {current.isVideo ? (
          <video
            ref={videoRef}
            src={current.url}
            className="max-w-full max-h-full object-contain rounded-lg"
            onEnded={handleVideoEnded}
            autoPlay
          />
        ) : (
          <div className="relative">
            <img src={current.url} alt={current.title} className="max-w-full max-h-[75vh] object-contain rounded-lg" />
            <div className="absolute bottom-0 left-0 right-0 h-1 bg-white/20 rounded-b-lg overflow-hidden">
              <div className="h-full bg-accent transition-all duration-100" style={{ width: `${progress}%` }} />
            </div>
          </div>
        )}
      </div>

      <div className="flex items-center gap-3 mt-4" onClick={(e) => e.stopPropagation()}>
        <button className="text-white/80 hover:text-white p-2" onClick={goPrev} disabled={currentIdx === 0}>
          <SkipBack size={20} />
        </button>
        <button className="text-white p-3 rounded-full bg-white/10 hover:bg-white/20" onClick={togglePlay}>
          {playing ? <Pause size={24} /> : <Play size={24} />}
        </button>
        <button className="text-white/80 hover:text-white p-2" onClick={goNext} disabled={currentIdx >= items.length - 1}>
          <SkipForward size={20} />
        </button>
      </div>

      <div className="mt-3 flex items-center gap-1 max-w-[80vw] overflow-x-auto no-scrollbar pb-2">
        {items.map((item, idx) => (
          <button
            key={item.id}
            className={`flex-shrink-0 w-14 h-10 rounded-md overflow-hidden border-2 transition-all ${
              idx === currentIdx ? 'border-accent scale-110' : 'border-transparent opacity-60 hover:opacity-100'
            }`}
            onClick={() => { setCurrentIdx(idx); setProgress(0); setPlaying(true); }}
          >
            {item.thumbnail ? (
              <img src={item.thumbnail} alt="" className="w-full h-full object-cover" />
            ) : (
              <div className="w-full h-full bg-white/10" />
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
