import { NODE_TYPE_CONFIG } from '@/utils/constants';
import type { NodeType } from '@/types';

const nodeTypes: NodeType[] = ['script', 'character', 'scene', 'storyboard', 'image', 'video', 'audio', 'group'];

export function NodePanel() {
  const handleDragStart = (e: React.DragEvent, type: string) => {
    e.dataTransfer.setData('nodeType', type);
    e.dataTransfer.effectAllowed = 'copy';
  };

  return (
    <div className="w-52 shrink-0 ml-4 my-4 rounded-2xl glass border border-panel-border shadow-soft flex flex-col">
      <div className="px-4 py-3 border-b border-panel-border">
        <h2 className="text-xs font-semibold text-theme-sub uppercase tracking-wider">节点库</h2>
      </div>
      <div className="flex-1 overflow-y-auto p-2.5 space-y-2">
        {nodeTypes.map((type) => {
          const cfg = NODE_TYPE_CONFIG[type];
          return (
            <div
              key={type}
              draggable
              onDragStart={(e) => handleDragStart(e, type)}
              className="group flex items-center gap-3 px-3 py-2.5 rounded-xl cursor-grab active:cursor-grabbing bg-panel-bg border border-panel-border hover:border-accent/30 hover:bg-panel-hover hover:-translate-y-0.5 transition-all duration-150 shadow-soft"
              title={cfg.desc}
            >
              <span
                className="w-9 h-9 rounded-xl flex items-center justify-center text-lg shrink-0"
                style={{ backgroundColor: `${cfg.color}18` }}
              >
                {cfg.icon}
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-theme-main">{cfg.label}</div>
                <div className="text-[10px] text-theme-sub truncate">{cfg.desc}</div>
              </div>
            </div>
          );
        })}
      </div>
      <div className="px-4 py-2.5 border-t border-panel-border text-[10px] text-theme-sub">
        拖拽节点到画布创建
      </div>
    </div>
  );
}
