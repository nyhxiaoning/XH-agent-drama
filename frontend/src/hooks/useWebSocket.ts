/**
 * P5: WebSocket 实时进度推送 Hook
 *
 * 连接到后端 WebSocket，实时接收任务进度更新。
 * 使用 wsIdRef 防止旧连接的回调污染新连接状态（重连循环 bug 根因）。
 * 客户端定时发送 ping 心跳，配合服务端 30s heartbeat 保持连接活跃。
 */
import { useEffect, useRef, useState, useCallback } from 'react';
import { useAuthStore } from '@/store/auth';

export interface TaskUpdate {
  type: string;
  task_id: string;
  node_id: string;
  canvas_id: string;
  status: string;
  progress: number;
  result: any;
  error: string | null;
  retry_count: number;
}

export interface HeartbeatMessage {
  type: 'heartbeat';
  ts: number;
}

export interface ConnectedMessage {
  type: 'connected';
  canvas_id?: string;
  message: string;
}

type WSMessage = TaskUpdate | HeartbeatMessage | ConnectedMessage | any;

interface UseWebSocketOptions {
  canvasId?: string;
  /** 当 false 时不建立连接（退出画布时传 false 断开 WS） */
  enabled?: boolean;
  onTaskUpdate?: (update: TaskUpdate) => void;
  /** 通用消息回调，接收所有 WebSocket 消息（包括任务更新、协作事件等） */
  onMessage?: (msg: WSMessage) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
}

interface UseWebSocketReturn {
  connected: boolean;
  lastMessage: WSMessage | null;
  send: (data: any) => void;
  reconnect: () => void;
}

const HEARTBEAT_INTERVAL_MS = 25000; // 客户端心跳间隔（服务端 30s，错开避免同步）
const MAX_RECONNECT_ATTEMPTS = 10;

/**
 * WebSocket 连接 Hook，支持自动重连。
 */
export function useWebSocket(options: UseWebSocketOptions = {}): UseWebSocketReturn {
  const { canvasId, enabled = true, onTaskUpdate, onMessage, onConnect, onDisconnect } = options;
  const [connected, setConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WSMessage | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reconnectAttempts = useRef(0);
  const callbacksRef = useRef({ onTaskUpdate, onMessage, onConnect, onDisconnect });
  /**
   * 每次 connect() 递增，事件回调通过比较 myId === wsIdRef.current
   * 判断自身是否为"当前活跃连接"。旧连接的 onclose/onopen 会被忽略，
   * 从根本上消除"旧连接回调污染新连接状态"导致的重连循环。
   */
  const wsIdRef = useRef(0);

  callbacksRef.current = { onTaskUpdate, onMessage, onConnect, onDisconnect };

  const connect = useCallback(() => {
    // 递增 ID，使旧连接的所有回调立即失效
    const myId = ++wsIdRef.current;

    // 关闭旧连接（其 onclose 会因 wsId 不匹配而被忽略）
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    // 清理待重连定时器
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }

    // 清理旧心跳定时器
    if (heartbeatTimerRef.current) {
      clearInterval(heartbeatTimerRef.current);
      heartbeatTimerRef.current = null;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const token = useAuthStore.getState().token || '';
    const wsUrl = canvasId
      ? `${protocol}//${host}/api/v1/ws/canvas/${canvasId}?token=${encodeURIComponent(token)}`
      : `${protocol}//${host}/api/v1/ws/global?token=${encodeURIComponent(token)}`;

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        if (wsIdRef.current !== myId) return; // 旧连接，忽略
        setConnected(true);
        reconnectAttempts.current = 0;
        callbacksRef.current.onConnect?.();

        // 启动客户端心跳：定期发送 ping 保持连接活跃
        heartbeatTimerRef.current = setInterval(() => {
          if (wsIdRef.current !== myId) return;
          if (wsRef.current?.readyState === WebSocket.OPEN) {
            try {
              wsRef.current.send(JSON.stringify({ type: 'ping', ts: Date.now() }));
            } catch {
              // send 失败不处理，onclose 会触发重连
            }
          }
        }, HEARTBEAT_INTERVAL_MS);
      };

      ws.onmessage = (event) => {
        if (wsIdRef.current !== myId) return; // 旧连接，忽略
        try {
          const data = JSON.parse(event.data) as WSMessage;
          setLastMessage(data);

          if (data.type === 'task_update' && callbacksRef.current.onTaskUpdate) {
            callbacksRef.current.onTaskUpdate(data as unknown as TaskUpdate);
          }
          if (callbacksRef.current.onMessage) {
            callbacksRef.current.onMessage(data);
          }
        } catch {
          // 忽略非 JSON 消息
        }
      };

      ws.onclose = () => {
        if (wsIdRef.current !== myId) return; // 旧连接（已被新连接取代），忽略
        setConnected(false);
        callbacksRef.current.onDisconnect?.();

        // 停止心跳
        if (heartbeatTimerRef.current) {
          clearInterval(heartbeatTimerRef.current);
          heartbeatTimerRef.current = null;
        }

        // 自动重连（指数退避）
        if (reconnectAttempts.current < MAX_RECONNECT_ATTEMPTS) {
          const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 30000);
          reconnectTimerRef.current = setTimeout(() => {
            if (wsIdRef.current !== myId) return; // 已被清理或替换，忽略
            reconnectAttempts.current++;
            connect();
          }, delay);
        }
      };

      ws.onerror = () => {
        // error 后通常会触发 onclose，无需额外处理
      };
    } catch {
      if (wsIdRef.current === myId) {
        setConnected(false);
      }
    }
  }, [canvasId, enabled]);

  useEffect(() => {
    // enabled 为 false 时不建立连接（退出画布场景）
    if (!enabled) {
      setConnected(false);
      return;
    }
    connect();

    return () => {
      // 递增 wsId 使所有待执行的回调立即失效（包括 setTimeout 中的）
      wsIdRef.current++;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (heartbeatTimerRef.current) {
        clearInterval(heartbeatTimerRef.current);
        heartbeatTimerRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  const send = useCallback((data: any) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(typeof data === 'string' ? data : JSON.stringify(data));
    }
  }, []);

  const reconnect = useCallback(() => {
    reconnectAttempts.current = 0;
    connect();
  }, [connect]);

  return { connected, lastMessage, send, reconnect };
}
