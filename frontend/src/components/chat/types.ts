/**
 * 聊天组件公共类型定义
 *
 * 统一 AgentChat 和 SkillChat 的消息类型，消除重复定义。
 */

/** 消息角色 */
export type ChatRole = 'user' | 'assistant' | 'progress' | 'error' | 'system';

/** 卡片类型（AgentChat 专用，SkillChat 可选） */
export type CardType =
  | 'parameter_pending'
  | 'planning_result'
  | 'asset_result'
  | 'production_result'
  | 'finalized_result'
  | 'feedback';

/** 统一聊天消息接口 */
export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  /** Agent 标识（如 script_planner, director_brain） */
  agent?: string;
  /** 步骤标识（如 planning, asset, production） */
  step?: string;
  /** 原始数据（用于结构化渲染） */
  rawData?: any;
  /** 卡片类型（AgentChat 结构化卡片用） */
  cardType?: CardType;
  /** 时间戳（毫秒） */
  timestamp: number;
}

/** Agent 元数据（图标、名称、颜色） */
export interface AgentMeta {
  name: string;
  icon: string; // lucide icon name
  gradient: string; // tailwind gradient classes
}
