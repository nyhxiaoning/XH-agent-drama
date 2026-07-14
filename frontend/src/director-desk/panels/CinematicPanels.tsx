import { useCallback } from "react";
import { Copy, Download, FileJson, FileText, Send } from "lucide-react";
import {
  InspectorPanel,
  InspectorRangeNumberField,
  InspectorSection,
  InspectorSelectField,
} from "./InspectorControls";
import { postCinematicParamsToHost } from "../io/hostBridge";
import {
  APERTURE_OPTIONS,
  COLOR_GRADE_OPTIONS,
  FOCAL_LENGTH_PRESETS,
  downloadTextFile,
  exportShotListCSV,
  exportShotListJSON,
  focalLengthToFov,
  fovToFocalLength,
  generateCinematicPrompt,
  getMotionMagnitude,
} from "../io/cinematicPromptExport";
import {
  CAMERA_MOVEMENT_CATEGORIES,
  CAMERA_MOVEMENT_PRESETS,
  getMovementPresetById,
} from "../presets/cameraMovementPresets";
import type { DirectorCameraShot } from "../schema/directorProject";
import { useDirectorStore } from "../store/directorStore";

function updateCameraCinematic(
  cameraId: string,
  patch: Partial<NonNullable<DirectorCameraShot["cinematic"]>>,
  updateCamera: (id: string, patch: Partial<DirectorCameraShot>) => void,
  camera: DirectorCameraShot
) {
  updateCamera(cameraId, {
    cinematic: { ...camera.cinematic, ...patch },
  });
}

/** 运镜 Tab 内容 */
export function MovementTabContent({ camera }: { camera: DirectorCameraShot }) {
  const updateCamera = useDirectorStore((state) => state.updateCamera);

  const handlePresetSelect = useCallback(
    (presetId: string) => {
      const currentPreset = getMovementPresetById(camera.cinematic?.movementPresetId);
      // 点击已选预设 → 取消选择
      if (currentPreset?.id === presetId) {
        updateCameraCinematic(camera.id, { movementPresetId: undefined }, updateCamera, camera);
      } else {
        updateCameraCinematic(camera.id, { movementPresetId: presetId }, updateCamera, camera);
      }
    },
    [camera, updateCamera]
  );

  const activePreset = getMovementPresetById(camera.cinematic?.movementPresetId);

  return (
    <div className="movement-tab-content">
      <InspectorSection title="运镜预设">
        {CAMERA_MOVEMENT_CATEGORIES.map((category) => {
          const presets = CAMERA_MOVEMENT_PRESETS.filter((p) => p.category === category.id);
          return (
            <div key={category.id} className="movement-category">
              <h4 className="movement-category-title">{category.label}</h4>
              <div className="movement-preset-grid">
                {presets.map((preset) => {
                  const isActive = activePreset?.id === preset.id;
                  return (
                    <button
                      key={preset.id}
                      type="button"
                      className={`movement-preset-card${isActive ? " is-active" : ""}`}
                      title={preset.description}
                      onClick={() => handlePresetSelect(preset.id)}
                    >
                      <span className="movement-preset-icon">{preset.icon}</span>
                      <span className="movement-preset-name">{preset.name}</span>
                      <span className="movement-preset-name-en">{preset.nameEn}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </InspectorSection>

      {activePreset && (
        <InspectorSection title="运镜详情">
          <div className="movement-detail">
            <div className="movement-detail-row">
              <span className="movement-detail-label">运镜</span>
              <span className="movement-detail-value">{activePreset.name} ({activePreset.nameEn})</span>
            </div>
            <div className="movement-detail-row">
              <span className="movement-detail-label">描述</span>
              <span className="movement-detail-value">{activePreset.description}</span>
            </div>
            <div className="movement-detail-row">
              <span className="movement-detail-label">运动幅度</span>
              <span className="movement-detail-value movement-magnitude-badge" data-magnitude={activePreset.motionMagnitude}>
                {activePreset.motionMagnitude}
              </span>
            </div>
            <div className="movement-detail-prompt">
              <span className="movement-detail-label">Prompt 片段</span>
              <code className="movement-detail-code">{activePreset.promptFragment}</code>
            </div>
          </div>
        </InspectorSection>
      )}
    </div>
  );
}

/** 影视参数 Tab 内容 */
export function CinematicTabContent({ camera }: { camera: DirectorCameraShot }) {
  const updateCamera = useDirectorStore((state) => state.updateCamera);
  const cameras = useDirectorStore((state) => state.project.cameras);

  const focalLength = camera.cinematic?.focalLength ?? Math.round(fovToFocalLength(camera.fov));
  const aperture = camera.cinematic?.aperture || "f/2.8";
  const colorGrade = camera.cinematic?.colorGrade || "natural";

  const handleFocalLengthChange = useCallback(
    (value: string) => {
      const mm = Number(value);
      if (!Number.isFinite(mm) || mm < 7 || mm > 300) return;
      const newFov = focalLengthToFov(mm);
      updateCameraCinematic(camera.id, { focalLength: mm }, updateCamera, camera);
      // 同步 FOV
      updateCamera(camera.id, { fov: Number(newFov.toFixed(1)) });
    },
    [camera, updateCamera]
  );

  const handleApertureChange = useCallback(
    (value: string) => {
      updateCameraCinematic(camera.id, { aperture: value }, updateCamera, camera);
    },
    [camera, updateCamera]
  );

  const handleColorGradeChange = useCallback(
    (value: string) => {
      updateCameraCinematic(camera.id, { colorGrade: value }, updateCamera, camera);
    },
    [camera, updateCamera]
  );

  const fullPrompt = generateCinematicPrompt(camera);
  const motionMagnitude = getMotionMagnitude(camera);

  const handleCopyPrompt = useCallback(() => {
    navigator.clipboard.writeText(fullPrompt).catch(() => {});
  }, [fullPrompt]);

  const handleExportCSV = useCallback(() => {
    const csv = exportShotListCSV(cameras);
    downloadTextFile(csv, "shot-list.csv", "text/csv");
  }, [cameras]);

  const handleExportJSON = useCallback(() => {
    const json = exportShotListJSON(cameras);
    downloadTextFile(json, "shot-list.json", "application/json");
  }, [cameras]);

  const handleSendToVideoNode = useCallback(() => {
    postCinematicParamsToHost({
      prompt: fullPrompt,
      motionMagnitude,
      cameraName: camera.name,
    });
  }, [fullPrompt, motionMagnitude, camera.name]);

  return (
    <div className="cinematic-tab-content">
      {/* 焦距 */}
      <InspectorSection title="焦距">
        <InspectorRangeNumberField
          label="焦距 (mm)"
          rangeAriaLabel="焦距滑杆"
          numberAriaLabel="焦距数值"
          min="7"
          max="300"
          step="1"
          value={focalLength}
          onValueChange={handleFocalLengthChange}
        />
        <div className="focal-length-presets">
          {FOCAL_LENGTH_PRESETS.map((preset) => (
            <button
              key={preset.mm}
              type="button"
              className={`focal-length-preset${focalLength === preset.mm ? " is-active" : ""}`}
              onClick={() => handleFocalLengthChange(String(preset.mm))}
            >
              <span className="focal-length-preset-mm">{preset.mm}mm</span>
              <span className="focal-length-preset-use">{preset.useCase}</span>
            </button>
          ))}
        </div>
      </InspectorSection>

      {/* 光圈 */}
      <InspectorSection title="光圈 & 景深">
        <InspectorSelectField
          label="光圈"
          ariaLabel="光圈选择"
          value={aperture}
          onChange={handleApertureChange}
          options={APERTURE_OPTIONS.map((a) => ({ value: a, label: a }))}
        />
      </InspectorSection>

      {/* 滤镜 */}
      <InspectorSection title="色彩滤镜">
        <div className="color-grade-grid">
          {COLOR_GRADE_OPTIONS.map((option) => (
            <button
              key={option.id}
              type="button"
              className={`color-grade-option${colorGrade === option.id ? " is-active" : ""}`}
              onClick={() => handleColorGradeChange(option.id)}
            >
              <span className="color-grade-icon">{option.icon}</span>
              <span className="color-grade-label">{option.label}</span>
            </button>
          ))}
        </div>
      </InspectorSection>

      {/* 生成 Prompt */}
      <InspectorSection title="运镜 Prompt">
        <div className="cinematic-prompt-preview">
          <code className="cinematic-prompt-code">{fullPrompt}</code>
        </div>
        <div className="cinematic-prompt-actions">
          <button
            type="button"
            className="cinematic-action-button"
            onClick={handleCopyPrompt}
          >
            <Copy size={14} />
            <span>复制 Prompt</span>
          </button>
          <button
            type="button"
            className="cinematic-action-button cinematic-action-primary"
            onClick={handleSendToVideoNode}
          >
            <Send size={14} />
            <span>发送到视频节点</span>
          </button>
        </div>
      </InspectorSection>

      {/* 镜头清单导出 */}
      <InspectorSection title="镜头清单导出">
        <div className="cinematic-prompt-actions">
          <button
            type="button"
            className="cinematic-action-button"
            onClick={handleExportCSV}
          >
            <FileText size={14} />
            <span>导出 CSV</span>
          </button>
          <button
            type="button"
            className="cinematic-action-button"
            onClick={handleExportJSON}
          >
            <FileJson size={14} />
            <span>导出 JSON</span>
          </button>
        </div>
      </InspectorSection>
    </div>
  );
}
