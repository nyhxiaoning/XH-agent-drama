import { Line } from "@react-three/drei";
import { useMemo } from "react";
import { Vector3 } from "three";
import { getMovementPresetById } from "../presets/cameraMovementPresets";
import type { DirectorCameraShot } from "../schema/directorProject";
import { getCameraViewSnapshotFromShot } from "../schema/cameraGeometry";

const PATH_COLOR = "#FFD700";
const KEYFRAME_COLOR = "#FF6B6B";

/**
 * 运镜路径预览组件
 * 在 3D 视口中渲染选中摄像机运镜预设的起止路径
 */
export function CameraPathPreview({ camera }: { camera: DirectorCameraShot }) {
  const preset = getMovementPresetById(camera.cinematic?.movementPresetId);

  const pathPoints = useMemo<{
    points: Vector3[];
    startPos: Vector3;
    endPos: Vector3;
    startTarget: Vector3;
    endTarget: Vector3;
  } | null>(() => {
    if (!preset) return null;

    // 获取摄像机当前视点位置（包含 frustum offset）
    const viewSnapshot = getCameraViewSnapshotFromShot(camera);
    const basePos = new Vector3(...viewSnapshot.position);
    const baseTarget = new Vector3(...viewSnapshot.target);

    const start = preset.keyframes.start;
    const end = preset.keyframes.end;

    // 起始位置 = 当前视点 + 偏移
    const startPos = basePos.clone().add(new Vector3(...start.positionOffset));
    const endPos = basePos.clone().add(new Vector3(...end.positionOffset));

    // 起始注视 = 当前注视 + 偏移
    const startTarget = baseTarget.clone().add(new Vector3(...start.targetOffset));
    const endTarget = baseTarget.clone().add(new Vector3(...end.targetOffset));

    // 生成插值路径点（用样条曲线模拟）
    const points: Vector3[] = [];
    const segments = 20;
    for (let i = 0; i <= segments; i++) {
      const t = i / segments;
      // 线性插值（简单版，后续可升级为 Catmull-Rom）
      const pos = startPos.clone().lerp(endPos, t);
      points.push(pos);
    }

    return { points, startPos, endPos, startTarget, endTarget };
  }, [camera, preset]);

  if (!preset || !pathPoints || pathPoints.points.length === 0) return null;

  const { points, startPos, endPos } = pathPoints;

  return (
    <group>
      {/* 路径线 */}
      <Line points={points} color={PATH_COLOR} lineWidth={2} dashed dashSize={0.15} gapSize={0.08} />

      {/* 起始关键帧标记 */}
      <mesh position={startPos}>
        <sphereGeometry args={[0.06, 12, 12]} />
        <meshBasicMaterial color={KEYFRAME_COLOR} />
      </mesh>

      {/* 终止关键帧标记 */}
      <mesh position={endPos}>
        <sphereGeometry args={[0.06, 12, 12]} />
        <meshBasicMaterial color={KEYFRAME_COLOR} />
      </mesh>

      {/* 方向箭头：从起点指向终点 */}
      {startPos.distanceTo(endPos) > 0.1 && (
        <Line
          points={[startPos, endPos]}
          color={PATH_COLOR}
          lineWidth={1}
          transparent
          opacity={0.3}
        />
      )}
    </group>
  );
}

/**
 * 渲染所有选中摄像机的运镜路径预览
 */
export function CameraPathPreviewLayer({ cameras }: { cameras: DirectorCameraShot[] }) {
  // 只渲染有运镜预设的摄像机
  const camerasWithMovement = cameras.filter(
    (cam) => cam.cinematic?.movementPresetId && getMovementPresetById(cam.cinematic.movementPresetId)
  );

  if (camerasWithMovement.length === 0) return null;

  return (
    <group>
      {camerasWithMovement.map((camera) => (
        <CameraPathPreview key={camera.id} camera={camera} />
      ))}
    </group>
  );
}
