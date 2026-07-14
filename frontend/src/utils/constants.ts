import type { NodeType } from '@/types';

export const NODE_TYPE_CONFIG: Record<NodeType, { label: string; icon: string; color: string; desc: string }> = {
  script: { label: '剧本', icon: '📝', color: '#525252', desc: '剧本/文案输入' },
  character: { label: '角色', icon: '👤', color: '#ec4899', desc: '角色设定' },
  scene: { label: '场景', icon: '🏞️', color: '#14b8a6', desc: '场景描述' },
  storyboard: { label: '分镜', icon: '🎬', color: '#f59e0b', desc: '分镜镜头' },
  image: { label: '图片', icon: '🖼️', color: '#3b82f6', desc: 'AI生图' },
  video: { label: '视频', icon: '🎥', color: '#ef4444', desc: 'AI生视频' },
  audio: { label: '音频', icon: '🎵', color: '#06b6d4', desc: 'AI生音频' },
  group: { label: '分组', icon: '📦', color: '#6b7280', desc: '节点分组' },
};

export const STATUS_CONFIG: Record<string, { label: string; color: string; bgClass: string }> = {
  pending: { label: '等待中', color: '#6b7280', bgClass: 'bg-node-pending' },
  processing: { label: '生成中', color: '#3b82f6', bgClass: 'bg-node-processing' },
  success: { label: '已完成', color: '#10b981', bgClass: 'bg-node-success' },
  failed: { label: '失败', color: '#ef4444', bgClass: 'bg-node-failed' },
};
