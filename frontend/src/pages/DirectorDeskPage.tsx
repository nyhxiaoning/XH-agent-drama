import { useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { DirectorDesk } from "@/director-desk";
import { useEditorStore } from "@/store/editor";
import { api } from "@/utils/api";
import { useTheme } from "@/hooks/useTheme";
import type { CinematicParamsPayload } from "@/director-desk/io/hostBridge";

export default function DirectorDeskPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const canvas = useEditorStore((s) => s.canvas);
  const addNode = useEditorStore((s) => s.addNode);
  const { theme } = useTheme();
  const sourceNodeId = searchParams.get("nodeId");
  const panoramaAUrl = searchParams.get("panorama");

  const handleCaptures = useCallback(async (captures: Array<{ dataUrl: string; fileName: string }>) => {
    if (!canvas) return;
    for (const capture of captures) {
      try {
        const blob = await (await fetch(capture.dataUrl)).blob();
        const file = new File([blob], capture.fileName, { type: "image/png" });
        const asset = await api.uploadAsset(file, {
          name: capture.fileName.replace(/\.png$/, ""),
          assetType: "image",
          canvasId: canvas.id,
        });
        const offset = Math.random() * 200 - 100;
        await addNode("image", 400 + offset, 300 + offset);
      } catch (e) {
        console.error("Failed to save capture:", e);
      }
    }
  }, [canvas, addNode]);

  const handleCinematicParams = useCallback(async (params: CinematicParamsPayload) => {
    if (!canvas) return;
    try {
      // 在画布上创建一个视频节点，并填入运镜 prompt
      const offset = Math.random() * 200 - 100;
      await addNode("video", 400 + offset, 300 + offset);
      const { canvas: updated } = useEditorStore.getState();
      const newNode = updated?.nodes[updated.nodes.length - 1];
      if (newNode) {
        await api.updateNode(newNode.id, {
          prompt: params.prompt,
          config: {
            ...(newNode.config || {}),
            generation_params: {
              ...((newNode.config as Record<string, unknown>)?.generation_params as Record<string, unknown> | undefined),
              motion_magnitude: params.motionMagnitude,
            },
          },
        });
        // 同步本地 store
        useEditorStore.setState((s) => ({
          canvas: s.canvas
            ? {
                ...s.canvas,
                nodes: s.canvas.nodes.map((n) =>
                  n.id === newNode.id
                    ? {
                        ...n,
                        prompt: params.prompt,
                        config: {
                          ...(n.config || {}),
                          generation_params: {
                            ...((n.config as Record<string, unknown>)?.generation_params as Record<string, unknown> | undefined),
                            motion_magnitude: params.motionMagnitude,
                          },
                        },
                      }
                    : n
                ),
              }
            : s.canvas,
        }));
      }
    } catch (e) {
      console.error("Failed to create video node from cinematic params:", e);
    }
  }, [canvas, addNode]);

  const handleClose = () => {
    navigate("/home");
  };

  return (
    <div className="fixed inset-0 z-[100] bg-black">
      <DirectorDesk
        theme={theme === "dark" ? "dark" : "light"}
        instanceId={canvas?.id || null}
        onCaptures={handleCaptures}
        onCinematicParams={handleCinematicParams}
        onClose={handleClose}
      />
    </div>
  );
}
