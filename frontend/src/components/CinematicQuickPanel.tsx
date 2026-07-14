import { useState, useCallback, useEffect } from 'react';
import { X, Film, Copy, Check } from 'lucide-react';
import type { CanvasNode } from '@/types';
import {
  CAMERA_MOVEMENT_PRESETS,
  CAMERA_MOVEMENT_CATEGORIES,
  getMovementPresetById,
  type CameraMovementPreset,
} from '@/director-desk/presets/cameraMovementPresets';
import {
  FOCAL_LENGTH_PRESETS,
  APERTURE_OPTIONS,
  COLOR_GRADE_OPTIONS,
} from '@/director-desk/io/cinematicPromptExport';

export interface CinematicQuickPanelProps {
  node: CanvasNode;
  onConfirm: (config: Record<string, unknown>) => void;
  onClose: () => void;
}

export function CinematicQuickPanel({ node, onConfirm, onClose }: CinematicQuickPanelProps) {
  // 从节点 config 读取已保存的影视参数
  const existingConfig = (node.config as Record<string, unknown>) || {};
  const [selectedPresetId, setSelectedPresetId] = useState<string | undefined>(
    existingConfig.cinematic_movementPresetId as string | undefined
  );
  const [focalLength, setFocalLength] = useState<number>(
    (existingConfig.cinematic_focalLength as number) || 35
  );
  const [aperture, setAperture] = useState<string>(
    (existingConfig.cinematic_aperture as string) || 'f/2.8'
  );
  const [colorGrade, setColorGrade] = useState<string>(
    (existingConfig.cinematic_colorGrade as string) || 'natural'
  );
  const [copied, setCopied] = useState(false);

  // ESC 关闭
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  const selectedPreset = getMovementPresetById(selectedPresetId);

  // 生成预览 prompt
  const previewPrompt = (() => {
    const parts: string[] = [];
    // 景别根据焦距推断
    const fov = 2 * Math.atan(36 / (2 * focalLength)) * (180 / Math.PI);
    let shotType = 'medium shot';
    if (fov <= 20) shotType = 'extreme close-up';
    else if (fov <= 35) shotType = 'close-up';
    else if (fov <= 55) shotType = 'medium shot';
    else if (fov <= 75) shotType = 'full shot';
    else shotType = 'wide shot';
    parts.push(shotType);
    parts.push(`${focalLength}mm cinematic lens`);
    const apertureDofMap: Record<string, string> = {
      'f/1.4': 'very shallow depth of field, creamy bokeh',
      'f/1.8': 'very shallow depth of field, smooth bokeh',
      'f/2.0': 'shallow depth of field, bokeh background',
      'f/2.8': 'shallow depth of field',
      'f/4.0': 'moderate shallow depth of field',
      'f/5.6': 'moderate depth of field',
      'f/8.0': 'deep depth of field, most elements in focus',
      'f/11': 'deep depth of field, everything in focus',
      'f/16': 'very deep depth of field, fully sharp',
    };
    if (apertureDofMap[aperture]) parts.push(apertureDofMap[aperture]);
    if (selectedPreset) {
      parts.push(selectedPreset.promptFragment);
    } else {
      parts.push('locked-off static camera with subtle micro-movement');
    }
    const colorGradeMap: Record<string, string> = {
      teal_orange: 'teal and orange color grading, blockbuster look',
      noir: 'high contrast black and white, film noir style',
      warm: 'warm golden tones, nostalgic feel',
      cool: 'cool blue tones, melancholic atmosphere',
      vintage: 'vintage film look, faded colors, grainy texture',
      natural: 'natural color grading, true to life',
    };
    if (colorGradeMap[colorGrade]) parts.push(colorGradeMap[colorGrade]);
    parts.push('35mm cinematic film grain, Kodak 5207');
    return parts.join(', ');
  })();

  const handleConfirm = useCallback(() => {
    onConfirm({
      cinematic_movementPresetId: selectedPresetId,
      cinematic_focalLength: focalLength,
      cinematic_aperture: aperture,
      cinematic_colorGrade: colorGrade,
      cinematic_prompt: previewPrompt,
    });
  }, [selectedPresetId, focalLength, aperture, colorGrade, previewPrompt, onConfirm]);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(previewPrompt).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }).catch(() => {});
  }, [previewPrompt]);

  // 按分类分组运镜预设
  const presetsByCategory = CAMERA_MOVEMENT_CATEGORIES.map((cat) => ({
    ...cat,
    presets: CAMERA_MOVEMENT_PRESETS.filter((p) => p.category === cat.id),
  }));

  return (
    <div
      className="fixed inset-0 z-[200] bg-black/70 backdrop-blur-sm flex items-center justify-center no-pan"
      onClick={onClose}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div
        className="relative bg-[#1a1a2e] rounded-2xl shadow-2xl border border-white/10 w-[90vw] max-w-[680px] max-h-[88vh] flex flex-col overflow-hidden no-pan"
        onClick={(e) => e.stopPropagation()}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-white/10 shrink-0">
          <div className="flex items-center gap-2 text-white">
            <Film size={20} className="text-amber-400" />
            <h2 className="text-base font-semibold">运镜 & 影视参数</h2>
            <span className="text-[11px] text-white/40 ml-2">{node.title}</span>
          </div>
          <button
            className="text-white/60 hover:text-white p-1 rounded-lg hover:bg-white/10 transition-colors"
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* 运镜预设 */}
          <div>
            <div className="text-[12px] text-white/60 font-semibold mb-2">运镜方式</div>
            <div className="space-y-3">
              {presetsByCategory.map((cat) => (
                <div key={cat.id}>
                  <div className="text-[10px] text-white/35 uppercase tracking-wider mb-1.5">{cat.label}</div>
                  <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
                    {cat.presets.map((preset: CameraMovementPreset) => {
                      const active = selectedPresetId === preset.id;
                      return (
                        <button
                          key={preset.id}
                          className={`relative rounded-xl border px-2.5 py-2 text-left transition-all ${
                            active
                              ? 'border-amber-400/60 bg-amber-400/10 ring-1 ring-amber-400/30'
                              : 'border-white/10 bg-white/5 hover:border-white/25 hover:bg-white/8'
                          }`}
                          onClick={() => {
                            setSelectedPresetId(active ? undefined : preset.id);
                          }}
                        >
                          <div className="flex items-center gap-1.5">
                            <span className="text-sm">{preset.icon}</span>
                            <span className={`text-[11px] font-medium ${active ? 'text-amber-300' : 'text-white/80'}`}>
                              {preset.name}
                            </span>
                          </div>
                          <div className="text-[9px] text-white/35 mt-0.5 truncate">{preset.nameEn}</div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* 焦距 */}
          <div>
            <div className="text-[12px] text-white/60 font-semibold mb-2">焦距 ({focalLength}mm)</div>
            <input
              type="range"
              min={7}
              max={300}
              step={1}
              value={focalLength}
              onChange={(e) => setFocalLength(Number(e.target.value))}
              className="w-full accent-amber-400"
            />
            <div className="flex flex-wrap gap-1.5 mt-2">
              {FOCAL_LENGTH_PRESETS.map((p) => (
                <button
                  key={p.mm}
                  className={`px-2.5 py-1 rounded-lg text-[10px] border transition-all ${
                    focalLength === p.mm
                      ? 'border-amber-400/60 bg-amber-400/10 text-amber-300'
                      : 'border-white/10 text-white/50 hover:border-white/25'
                  }`}
                  onClick={() => setFocalLength(p.mm)}
                  title={p.label}
                >
                  {p.mm}mm
                </button>
              ))}
            </div>
          </div>

          {/* 光圈 */}
          <div>
            <div className="text-[12px] text-white/60 font-semibold mb-2">光圈</div>
            <div className="flex flex-wrap gap-1.5">
              {APERTURE_OPTIONS.map((a) => (
                <button
                  key={a}
                  className={`px-3 py-1.5 rounded-lg text-[11px] border transition-all ${
                    aperture === a
                      ? 'border-amber-400/60 bg-amber-400/10 text-amber-300'
                      : 'border-white/10 text-white/50 hover:border-white/25'
                  }`}
                  onClick={() => setAperture(a)}
                >
                  {a}
                </button>
              ))}
            </div>
          </div>

          {/* 滤镜 */}
          <div>
            <div className="text-[12px] text-white/60 font-semibold mb-2">色彩滤镜</div>
            <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
              {COLOR_GRADE_OPTIONS.map((opt) => (
                <button
                  key={opt.id}
                  className={`rounded-xl border px-2 py-2 text-center transition-all ${
                    colorGrade === opt.id
                      ? 'border-amber-400/60 bg-amber-400/10'
                      : 'border-white/10 hover:border-white/25'
                  }`}
                  onClick={() => setColorGrade(opt.id)}
                >
                  <div className="text-base">{opt.icon}</div>
                  <div className={`text-[10px] mt-0.5 ${colorGrade === opt.id ? 'text-amber-300' : 'text-white/50'}`}>
                    {opt.label}
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* 生成 Prompt 预览 */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <div className="text-[12px] text-white/60 font-semibold">生成 Prompt 预览</div>
              <button
                className="flex items-center gap-1 text-[10px] text-white/40 hover:text-white/70 transition-colors"
                onClick={handleCopy}
              >
                {copied ? <Check size={12} className="text-green-400" /> : <Copy size={12} />}
                {copied ? '已复制' : '复制'}
              </button>
            </div>
            <div className="rounded-xl bg-black/30 border border-white/10 p-3 text-[11px] text-white/70 leading-relaxed font-mono max-h-24 overflow-y-auto">
              {previewPrompt}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-white/10 flex justify-end gap-2 shrink-0">
          <button
            className="px-4 py-2 rounded-lg text-[12px] text-white/50 hover:text-white/80 hover:bg-white/5 transition-colors"
            onClick={onClose}
          >
            取消
          </button>
          <button
            className="px-5 py-2 rounded-lg text-[12px] bg-amber-500/80 hover:bg-amber-500 text-white font-medium transition-colors"
            onClick={handleConfirm}
          >
            确认
          </button>
        </div>
      </div>
    </div>
  );
}
