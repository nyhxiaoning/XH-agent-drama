import { useAuthStore } from '@/store/auth';

const API_BASE = '/api/v1';

export function getAuthHeaders(isFormData = false): Record<string, string> {
  const token = useAuthStore.getState().token;
  const headers: Record<string, string> = {};
  if (!isFormData) {
    headers['Content-Type'] = 'application/json';
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const fullUrl = url.startsWith('http') ? url : `${API_BASE}${url}`;
  const isFormData = typeof FormData !== 'undefined' && options?.body instanceof FormData;
  const res = await fetch(fullUrl, {
    ...options,
    headers: {
      ...getAuthHeaders(isFormData),
      ...(options?.headers || {}),
    },
  });
  if (!res.ok) {
    // 401: Token 过期或无效，自动清除登录状态并跳转登录页
    if (res.status === 401) {
      useAuthStore.getState().setToken(null);
      useAuthStore.getState().setUser(null);
      // 避免在登录页重复跳转
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login?expired=1';
      }
    }
    const text = await res.text().catch(() => '');
    let err: { message?: string; detail?: string } = {};
    try { err = text ? JSON.parse(text) : {}; } catch {}
    throw new Error(err.message || err.detail || `请求失败 (${res.status})`);
  }
  const text = await res.text();
  if (!text) return undefined as T;
  try { return JSON.parse(text); } catch { return undefined as T; }
}

export interface LoginRes {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface User {
  id: string;
  name: string | null;
  email: string | null;
  phone: string | null;
  avatar_url: string | null;
  is_admin: boolean;
  is_active: boolean;
  credits: number;
  created_at: string;
}

export interface UserStats {
  canvas_count: number;
  image_count: number;
  video_count: number;
  script_count: number;
  audio_count: number;
  credits_used_this_month: number;
  total_recharged: number;
}

export interface CreditLedgerEntry {
  id: string;
  amount: number;
  balance_after: number;
  reason: string;
  description: string | null;
  created_at: string;
}

export interface CreditLedgerList {
  total: number;
  items: CreditLedgerEntry[];
  balance: number;
}

export interface CreditEstimate {
  task_type: string;
  cost: number;
  model: string | null;
  duration: number | null;
  resolution: string | null;
}

export interface RechargeTier {
  id: string;
  yuan: number;
  credits: number;
  enabled: boolean;
  order: number;
}

export interface Announcement {
  id: string;
  title: string;
  content: string;
  type: string;
  pinned: boolean;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface AnnouncementList {
  total: number;
  items: Announcement[];
}

export interface PaymentOrder {
  order_id: string;
  out_trade_no: string;
  channel: string;
  amount_yuan: number;
  credits: number;
  pay_url?: string;
  pay_code_url?: string;
}

export interface AdminUser {
  id: string;
  name: string | null;
  email: string | null;
  phone: string | null;
  credits: number;
  is_admin: boolean;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface AdminOrder {
  id: string;
  user_id: string;
  channel: string;
  out_trade_no: string;
  amount_yuan: number;
  credits: number;
  status: string;
  trade_no: string | null;
  paid_at: string | null;
  created_at: string;
}

export interface AdminOrderList {
  total: number;
  items: AdminOrder[];
}

export interface AdminLedgerEntry {
  id: string;
  user_id: string;
  amount: number;
  balance_after: number;
  reason: string;
  ref_id: string | null;
  description: string | null;
  created_at: string;
}

export interface AdminLedgerList {
  total: number;
  items: AdminLedgerEntry[];
}

export interface AdminStats {
  total_users: number;
  today_active_users: number;
  week_active_users: number;
  total_images: number;
  total_videos: number;
  total_scripts: number;
  total_recharged_yuan: number;
  today_recharged_yuan: number;
  week_recharged_yuan: number;
  model_ranking: { model: string; count: number }[];
}

export interface RedeemCode {
  id: string;
  code: string;
  points: number;
  batch_id: string | null;
  note: string | null;
  expires_at: string | null;
  used_at: string | null;
  used_by_id: string | null;
  created_at: string;
}

export interface RedeemCodeList {
  total: number;
  items: RedeemCode[];
}

export interface ModelConfig {
  id: string;
  model_id: string;
  name: string;
  type: string;
  description: string | null;
  enabled: boolean;
  order: number;
  credits: number;
  credits_5s: number;
  credits_10s: number;
  credits_15s: number;
}

export interface ModelPricing {
  model_id: string;
  type: string;
  credits: number;
  credits_5s: number;
  credits_10s: number;
  credits_15s: number;
}

export interface EnabledModel {
  model_id: string;
  name: string;
  type: string;
}

export interface RuntimeModelItem {
  model_id: string;
  label: string;
  provider: string;
  type: string;
}

export interface RuntimeModelsResponse {
  llm_models: RuntimeModelItem[];
  image_models: RuntimeModelItem[];
  video_models: RuntimeModelItem[];
  audio_models: RuntimeModelItem[];
  default_llm_model: string;
  llm_provider: string;
}

export interface LlmModel {
  model_id: string;
  name: string;
  description: string | null;
}

export const api = {
  health: () =>
    fetch('/health').then((r) => r.json()),

  // Auth
  register: (email: string, password: string, name?: string) =>
    request<User>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password, name }),
    }),
  login: (payload: { email: string; password: string } | { phone: string; password: string }) =>
    request<LoginRes>('/auth/login', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  sendSms: (phone: string, turnstileToken: string) =>
    request('/auth/send-sms', {
      method: 'POST',
      body: JSON.stringify({ phone, turnstile_token: turnstileToken }),
    }),
  loginSms: (phone: string, code: string, name?: string, password?: string) =>
    request<LoginRes>('/auth/login-sms', {
      method: 'POST',
      body: JSON.stringify({ phone, code, name, password }),
    }),
  me: () => request<User>('/users/me'),

  // User
  getMyStats: () => request<UserStats>('/users/me/stats'),
  changePassword: (currentPassword: string | null, newPassword: string) =>
    request('/users/me/password', {
      method: 'PUT',
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }),
  getMyLedger: (limit?: number, offset?: number) =>
    request<CreditLedgerList>(`/users/me/ledger?limit=${limit || 20}&offset=${offset || 0}`),
  redeemCode: (code: string) =>
    request<{ points: number; balance_after: number }>('/users/me/redeem', {
      method: 'POST',
      body: JSON.stringify({ code }),
    }),

  // Credits
  getCreditsBalance: () => request<{ user_id: string; balance: number }>('/credits/balance'),
  getCreditsLedger: (limit?: number, offset?: number) =>
    request<CreditLedgerEntry[]>(`/credits/ledger?limit=${limit || 50}&offset=${offset || 0}`),
  getCreditsPricing: () => request<{ pricing: Record<string, unknown> }>('/credits/pricing'),
  getModelPricing: () => request<ModelPricing[]>('/credits/model-pricing'),
  getEnabledModels: () => request<EnabledModel[]>('/credits/enabled-models'),
  getRuntimeModels: () => request<RuntimeModelsResponse>('/config/runtime-models'),
  estimateCreditCost: (taskType: string, nodeConfig?: Record<string, unknown>) =>
    request<CreditEstimate>(`/credits/estimate?task_type=${encodeURIComponent(taskType)}`, {
      method: 'POST',
      body: JSON.stringify(nodeConfig || {}),
    }),

  // Recharge / announcements
  getRechargeTiers: () => request<RechargeTier[]>('/recharge/tiers'),
  getAnnouncements: () => request<Announcement[]>('/announcements'),

  // Payments
  createPaymentOrder: (channel: 'alipay' | 'wechat', tierId: string) =>
    request<PaymentOrder>(`/payments/orders/${channel}`, {
      method: 'POST',
      body: JSON.stringify({ tier_id: tierId }),
    }),
  getOrderStatus: (outTradeNo: string) =>
    request<{ order_id: string; status: string; amount_yuan: number; credits: number; paid_at: string | null }>(
      `/payments/orders/${outTradeNo}/status`
    ),

  listCanvases: () => request<CanvasListItem[]>('/canvases'),
  createCanvas: (name: string, description?: string, teamId?: string) =>
    request<{ id: string }>('/canvases', { method: 'POST', body: JSON.stringify({ name, description, team_id: teamId }) }),
  getCanvas: (id: string) => request<Canvas>(`/canvases/${id}`),
  deleteCanvas: (id: string) =>
    request(`/canvases/${id}`, { method: 'DELETE' }),
  updateCanvasName: (id: string, name: string) =>
    request(`/canvases/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) }),

  createNode: (data: Partial<CanvasNode>) =>
    request<CanvasNode>('/nodes', { method: 'POST', body: JSON.stringify(data) }),
  updateNode: (id: string, data: Partial<CanvasNode>) =>
    request<CanvasNode>(`/nodes/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteNode: (id: string) => request(`/nodes/${id}`, { method: 'DELETE' }),
  batchUpdatePositions: (positions: { id: string; x: number; y: number }[]) =>
    request('/nodes/batch/positions', { method: 'POST', body: JSON.stringify(positions) }),
  nodeAction: (id: string, action: string, prompt?: string, style?: string, count?: number, config?: Record<string, unknown>) =>
    request(`/nodes/${id}/action`, {
      method: 'POST',
      body: JSON.stringify({ action, prompt, style, count, config }),
    }),

  // 预设功能
  executePreset: (featureId: string, opts: {
    nodeId?: string;
    canvasId?: string;
    prompt?: string;
    style?: string;
    config?: Record<string, unknown>;
    gridRows?: number;
    gridCols?: number;
    cropRegion?: { x: number; y: number; w: number; h: number };
  }) =>
    request<{ task_ids: string[]; node_ids: string[]; status: string; cost: number; message: string }>('/nodes/preset', {
      method: 'POST',
      body: JSON.stringify({
        feature_id: featureId,
        node_id: opts.nodeId,
        canvas_id: opts.canvasId,
        prompt: opts.prompt,
        style: opts.style,
        config: opts.config,
        grid_rows: opts.gridRows,
        grid_cols: opts.gridCols,
        crop_region: opts.cropRegion,
      }),
    }),

  // 25宫格分镜：任务完成后创建节点
  createStoryboard25Nodes: (nodeId: string) =>
    request<{ status: string; node_ids: string[]; count: number; message: string }>('/nodes/preset/storyboard_25/create_nodes', {
      method: 'POST',
      body: JSON.stringify({ feature_id: 'storyboard_25', node_id: nodeId }),
    }),

  createEdge: (data: Partial<CanvasEdge>) =>
    request<CanvasEdge>('/edges', { method: 'POST', body: JSON.stringify(data) }),
  updateEdge: (id: string, data: Partial<CanvasEdge>) =>
    request<CanvasEdge>(`/edges/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteEdge: (id: string) => request(`/edges/${id}`, { method: 'DELETE' }),

  getTasks: (canvasId?: string) => {
    const q = canvasId ? `?canvas_id=${canvasId}` : '';
    return request<TaskInfo[]>(`/tasks${q}`);
  },
  cancelTask: (id: string) => request(`/tasks/${id}/cancel`, { method: 'POST' }),
  /** #17 获取生成队列状态 */
  getQueueStatus: (canvasId?: string) => {
    const q = canvasId ? `?canvas_id=${canvasId}` : '';
    return request<{
      total: number; pending: number; running: number;
      success: number; failed: number; cancelled: number;
      max_concurrent: number;
      pending_details: Array<{ task_id: string; node_id: string; task_type: string; priority: number; created_at: string }>;
      running_details: Array<{ task_id: string; node_id: string; task_type: string; started_at: string | null; progress: number }>;
    }>(`/tasks/queue/status${q}`);
  },
  /** #17 按画布批量取消任务 */
  cancelTasksByCanvas: (canvasId: string) =>
    request<{ canvas_id: string; cancelled_count: number; cancelled_ids: string[] }>(
      `/tasks/cancel-by-canvas?canvas_id=${canvasId}`,
      { method: 'POST' }
    ),

  createSnapshot: (canvasId: string, label?: string) =>
    request(`/canvases/${canvasId}/snapshots`, {
      method: 'POST',
      body: JSON.stringify({ label: label || '' }),
    }),
  listSnapshots: (canvasId: string) =>
    request<{ id: string; label: string; created_at: string }[]>(`/canvases/${canvasId}/snapshots`),
  restoreSnapshot: (canvasId: string, snapshotId: string) =>
    request(`/canvases/${canvasId}/snapshots/${snapshotId}/restore`, { method: 'POST' }),

  getNodeContext: (nodeId: string) => request(`/agent/context/${nodeId}`),

  // Asset library
  listAssets: (assetType?: string, query?: string, canvasId?: string, teamId?: string) => {
    const params = new URLSearchParams();
    if (assetType && assetType !== 'all') params.append('asset_type', assetType);
    if (query) params.append('q', query);
    if (canvasId && canvasId !== 'undefined') params.append('canvas_id', canvasId);
    if (teamId && teamId !== 'undefined') params.append('team_id', teamId);
    const q = params.toString() ? `?${params.toString()}` : '';
    return request<Asset[]>(`/assets${q}`);
  },

  uploadAsset: (file: File, options?: { name?: string; assetType?: string; description?: string; canvasId?: string; teamId?: string }) => {
    const formData = new FormData();
    formData.append('file', file);
    if (options?.name) formData.append('name', options.name);
    if (options?.assetType) formData.append('asset_type', options.assetType);
    if (options?.description) formData.append('description', options.description);
    if (options?.canvasId) formData.append('canvas_id', options.canvasId);
    if (options?.teamId) formData.append('team_id', options.teamId);
    return request<Asset>('/assets/upload', {
      method: 'POST',
      body: formData,
    });
  },

  deleteAsset: (assetId: string) =>
    request<void>(`/assets/${assetId}`, { method: 'DELETE' }),

  // Team collaboration
  listTeams: () => request<{ teams: Team[]; total: number }>('/teams'),
  createTeam: (name: string) => request<Team>('/teams', { method: 'POST', body: JSON.stringify({ name }) }),
  joinTeam: (teamCode: string) => request<{ status: string; team_id: string; team_name: string }>('/teams/join', { method: 'POST', body: JSON.stringify({ team_code: teamCode }) }),
  getTeam: (teamId: string) => request<Team>(`/teams/${teamId}`),
  updateTeam: (teamId: string, name: string) => request<Team>(`/teams/${teamId}`, { method: 'PUT', body: JSON.stringify({ name }) }),
  deleteTeam: (teamId: string) => request<void>(`/teams/${teamId}`, { method: 'DELETE' }),
  updateTeamMemberRole: (teamId: string, userId: string, role: string) => request<TeamMember>(`/teams/${teamId}/members/${userId}/role`, { method: 'PUT', body: JSON.stringify({ role }) }),
  removeTeamMember: (teamId: string, userId: string) => request<void>(`/teams/${teamId}/members/${userId}`, { method: 'DELETE' }),

  // Short Drama Agent Workflow
  shortDramaStart: (prompt: string, mode?: string, scriptText?: string, llmModel?: string, teamId?: string) =>
    request<{ session_id: string; session: AgentSession }>('/agent/short-drama/start', {
      method: 'POST',
      body: JSON.stringify({ prompt, mode: mode || 'inspiration', script_text: scriptText, llm_model: llmModel, team_id: teamId }),
    }),
  shortDramaStep: (sessionId: string, step: string) =>
    request<{ step: string; data: Record<string, unknown>; session: AgentSession }>(
      '/agent/short-drama/step',
      { method: 'POST', body: JSON.stringify({ session_id: sessionId, step }) }
    ),
  shortDramaStepStream: async (
    sessionId: string,
    step: string,
    onMessage: (msg: WorkflowMessage) => void,
    onDone: () => void,
    onError: (err: string) => void,
    signal?: AbortSignal
  ): Promise<void> => {
    const url = `${API_BASE}/agent/short-drama/step/stream?session_id=${encodeURIComponent(sessionId)}&step=${encodeURIComponent(step)}`;
    try {
      const res = await fetch(url, { headers: getAuthHeaders(), signal });
      if (!res.ok) {
        onError(`请求失败 (${res.status})`);
        return;
      }
      if (!res.body) {
        onError('响应体为空');
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data:')) continue;
          const payload = trimmed.slice(5).trim();
          if (!payload) continue;
          try {
            const data = JSON.parse(payload) as WorkflowMessage;
            if (data.step === 'error') {
              onError(data.content || '阶段执行失败');
              return;
            }
            if (data.step === `${step}_done`) {
              onDone();
              return;
            }
            onMessage(data);
          } catch {
            // ignore parse errors
          }
        }
      }
      onDone();
    } catch (e: any) {
      if (e?.name === 'AbortError') return;
      onError(e?.message || 'SSE 连接异常');
    }
  },
  shortDramaLockAssets: (sessionId: string, charIds: string[], sceneIds: string[]) =>
    request<{ locked_assets: LockedAsset[]; asset_ids: string[]; session: AgentSession }>(
      '/agent/short-drama/lock-assets',
      {
        method: 'POST',
        body: JSON.stringify({ session_id: sessionId, char_ids: charIds, scene_ids: sceneIds }),
      }
    ),
  shortDramaSetOption: (sessionId: string, key: string, value: string) =>
    request<{ session: AgentSession }>('/agent/short-drama/option', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, key, value }),
    }),
  shortDramaFeedback: (sessionId: string, feedback: string, targetStage?: string) =>
    request<{ session: AgentSession }>('/agent/short-drama/feedback', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, feedback, target_stage: targetStage }),
    }),
  shortDramaSuggestParameters: (sessionId: string) =>
    request<{ status: string; suggestions: Record<string, string> }>(
      '/agent/short-drama/parameters/suggest',
      { method: 'POST', body: JSON.stringify({ session_id: sessionId }) }
    ),
  shortDramaConfirmParameters: (sessionId: string, globalParams: Record<string, string>, llmModel?: string) =>
    request<{ status: string; global_params: Record<string, string>; session: AgentSession }>(
      '/agent/short-drama/parameters/confirm',
      { method: 'POST', body: JSON.stringify({ session_id: sessionId, global_params: globalParams, llm_model: llmModel }) }
    ),
  shortDramaFinalize: (sessionId: string, canvasId?: string, autoGenerate: boolean = false) =>
    request<{ canvas_id: string; node_count: number; edge_count: number; auto_generated: boolean; auto_generated_node_ids: string[]; session: AgentSession }>(
      '/agent/short-drama/finalize',
      { method: 'POST', body: JSON.stringify({ session_id: sessionId, canvas_id: canvasId, auto_generate: autoGenerate }) }
    ),
  /** #13 增量同步会话数据到已有画布 */
  syncSessionToCanvas: (sessionId: string, canvasId: string) =>
    request<{ status: string; canvas_id: string; updated_count: number; created_count: number; edge_count: number }>(
      '/agent/short-drama/sync-canvas',
      { method: 'POST', body: JSON.stringify({ session_id: sessionId, canvas_id: canvasId }) }
    ),
  getShortDramaSession: (sessionId: string) =>
    request<{ session: AgentSession }>(`/agent/short-drama/session/${sessionId}`),

  // 强制解锁会话（诊断/恢复用）
  forceUnlockSession: (sessionId: string) =>
    request<{ status: string; message: string; session: AgentSession }>(
      `/agent/short-drama/force-unlock?session_id=${encodeURIComponent(sessionId)}`,
      { method: 'POST' }
    ),

  // LLM 诊断 ping
  llmPing: () =>
    request<{ status: string; elapsed_seconds?: number; config?: Record<string, unknown>; error?: string; error_type?: string; hint?: string }>('/agent/llm-ping'),

  // 轻量分镜模式
  liteStoryboardStart: (scriptText: string, storyType?: string, artStyle?: string, llmModel?: string, teamId?: string) =>
    request<{ session_id: string; session: AgentSession }>('/agent/short-drama/lite-storyboard', {
      method: 'POST',
      body: JSON.stringify({ script_text: scriptText, story_type: storyType, art_style: artStyle, llm_model: llmModel, team_id: teamId }),
    }),
  liteStoryboardStream: async (
    sessionId: string,
    onMessage: (msg: WorkflowMessage) => void,
    onDone: () => void,
    onError: (err: string) => void,
    signal?: AbortSignal
  ): Promise<void> => {
    const url = `${API_BASE}/agent/short-drama/lite-storyboard/stream?session_id=${encodeURIComponent(sessionId)}`;
    try {
      const res = await fetch(url, { headers: getAuthHeaders(), signal });
      if (!res.ok) { onError(`请求失败 (${res.status})`); return; }
      if (!res.body) { onError('响应体为空'); return; }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data:')) continue;
          const payload = trimmed.slice(5).trim();
          if (!payload) continue;
          try {
            const data = JSON.parse(payload) as WorkflowMessage;
            if (data.step === 'error') { onError(data.content || '轻量分镜失败'); return; }
            if (data.step === 'lite_storyboard_done') { onDone(); return; }
            onMessage(data);
          } catch { /* ignore parse errors */ }
        }
      }
      onDone();
    } catch (e: any) {
      if (e?.name === 'AbortError') return;
      onError(e?.message || 'SSE 连接异常');
    }
  },

  // 一键创作模式
  oneClickStart: (prompt: string, mode?: string, scriptText?: string, llmModel?: string, teamId?: string) =>
    request<{ session_id: string; session: AgentSession }>('/agent/short-drama/one-click', {
      method: 'POST',
      body: JSON.stringify({ prompt, mode: mode || 'inspiration', script_text: scriptText, llm_model: llmModel, team_id: teamId }),
    }),
  oneClickStream: async (
    sessionId: string,
    onMessage: (msg: WorkflowMessage) => void,
    onDone: (canvasId?: string) => void,
    onError: (err: string) => void,
    signal?: AbortSignal
  ): Promise<void> => {
    const url = `${API_BASE}/agent/short-drama/one-click/stream?session_id=${encodeURIComponent(sessionId)}`;
    try {
      const res = await fetch(url, { headers: getAuthHeaders(), signal });
      if (!res.ok) { onError(`请求失败 (${res.status})`); return; }
      if (!res.body) { onError('响应体为空'); return; }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data:')) continue;
          const payload = trimmed.slice(5).trim();
          if (!payload) continue;
          try {
            const data = JSON.parse(payload) as WorkflowMessage;
            if (data.step === 'error') { onError(data.content || '一键创作失败'); return; }
            if (data.step === 'one_click_done') {
              const canvasId = data.payload?.canvas_id as string | undefined;
              onDone(canvasId); return;
            }
            onMessage(data);
          } catch { /* ignore parse errors */ }
        }
      }
      onDone();
    } catch (e: any) {
      if (e?.name === 'AbortError') return;
      onError(e?.message || 'SSE 连接异常');
    }
  },

  // Enhanced features (P3/P6/P8/P9/P10/P11)
  getStyleTemplates: () => request<{ templates: StyleTemplate[] }>('/enhanced/style-templates'),
  applyStyleTemplate: (templateId: string, existingParams?: Record<string, string>) =>
    request<{ global_params: Record<string, string>; style_metadata: StyleMetadata }>('/enhanced/style-templates/apply', {
      method: 'POST',
      body: JSON.stringify({ template_id: templateId, existing_params: existingParams }),
    }),
  listSessionVersions: (sid: string) =>
    request<{ versions: SessionVersion[] }>(`/enhanced/sessions/${sid}/versions`),
  restoreSessionVersion: (sid: string, versionId: string) =>
    request<{ status: string; message: string }>(`/enhanced/sessions/${sid}/versions/restore`, {
      method: 'POST',
      body: JSON.stringify({ version_id: versionId }),
    }),
  diffSessionVersions: (sid: string, versionA: string, versionB: string) =>
    request<{ diff: Record<string, unknown> }>(`/enhanced/sessions/${sid}/versions/diff?version_a=${versionA}&version_b=${versionB}`),
  novelImportPlan: (novelText: string, targetEpisodes?: number, genreHint?: string, llmModel?: string) =>
    request<{ plan: NovelImportPlan }>('/enhanced/novel-import/plan', {
      method: 'POST',
      body: JSON.stringify({ novel_text: novelText, target_episodes: targetEpisodes || 10, genre_hint: genreHint, llm_model: llmModel }),
    }),
  novelGenerateEpisodeScript: (episodePlan: NovelImportPlan, sourceText: string, episodeNum: number, llmModel?: string) =>
    request<{ script: EpisodeScript }>('/enhanced/novel-import/episode-script', {
      method: 'POST',
      body: JSON.stringify({ episode_plan: episodePlan, source_text: sourceText, episode_num: episodeNum, llm_model: llmModel }),
    }),
  verifyCharacter: (name: string, desc: string, refUrl?: string, llmModel?: string) =>
    request<{ result: CharacterVerifyResult }>('/enhanced/consistency/verify-character', {
      method: 'POST',
      body: JSON.stringify({ character_name: name, character_desc: desc, reference_image_url: refUrl, llm_model: llmModel }),
    }),
  batchVerifyCharacters: (characters: CharacterVerifyInput[], llmModel?: string) =>
    request<{ results: CharacterVerifyResult[] }>('/enhanced/consistency/batch-verify', {
      method: 'POST',
      body: JSON.stringify({ characters, llm_model: llmModel }),
    }),
  checkStoryboardConsistency: (storyboard: StoryboardPanel[], characterAssets: CharacterAsset[], llmModel?: string) =>
    request<{ result: ConsistencyCheckResult }>('/enhanced/consistency/storyboard-check', {
      method: 'POST',
      body: JSON.stringify({ storyboard, character_assets: characterAssets, llm_model: llmModel }),
    }),
  listIpAssets: (params?: { asset_type?: string; style_tag?: string; genre_tag?: string; search?: string; is_public?: boolean; limit?: number; offset?: number }) => {
    const sp = new URLSearchParams();
    if (params?.asset_type) sp.append('asset_type', params.asset_type);
    if (params?.style_tag) sp.append('style_tag', params.style_tag);
    if (params?.genre_tag) sp.append('genre_tag', params.genre_tag);
    if (params?.search) sp.append('search', params.search);
    if (params?.is_public !== undefined) sp.append('is_public', String(params.is_public));
    if (params?.limit) sp.append('limit', String(params.limit));
    if (params?.offset !== undefined) sp.append('offset', String(params.offset));
    const query = sp.toString() ? `?${sp.toString()}` : '';
    return request<{ items: IpAsset[]; total: number; limit: number; offset: number }>(`/enhanced/ip-assets${query}`);
  },
  createIpAsset: (data: IpAssetCreate) =>
    request<{ id: string; status: string }>('/enhanced/ip-assets', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  reuseIpAsset: (assetId: string) =>
    request<{ status: string }>(`/enhanced/ip-assets/${assetId}/reuse`, { method: 'POST' }),
  listCollaborators: (canvasId: string) =>
    request<{ collaborators: Collaborator[] }>(`/enhanced/collaboration/${canvasId}/collaborators`),
  inviteCollaborator: (canvasId: string, username: string, role: string = 'viewer') =>
    request<{ status: string; message: string }>('/enhanced/collaboration/invite', {
      method: 'POST',
      body: JSON.stringify({ canvas_id: canvasId, username, role }),
    }),
  updateCollaboratorRole: (collabId: string, role: string) =>
    request<{ status: string }>(`/enhanced/collaboration/${collabId}/role`, {
      method: 'PUT',
      body: JSON.stringify({ role }),
    }),
  removeCollaborator: (collabId: string) =>
    request<{ status: string }>(`/enhanced/collaboration/${collabId}`, { method: 'DELETE' }),
  getWsStatus: () => request<{ connection_count: number; canvases: string[] }>('/enhanced/ws/status'),

  // Skill platform (through brain)
  listLlmModels: () => request<LlmModel[]>('/agent/llm-models'),
  listSkills: () => request<{ skills: any[] }>('/agent/skills'),
  runSkill: (skillId: string, prompt: string, params?: Record<string, string>, globalParams?: Record<string, string>) =>
    request<{ status: string; skill_id: string; params: Record<string, string>; data: SkillResultData }>('/agent/skills/run', {
      method: 'POST',
      body: JSON.stringify({ skill_id: skillId, prompt, params, global_params: globalParams }),
    }),
    runSkillStream: async (
      skillId: string,
      prompt: string,
      params: Record<string, string>,
      globalParams: Record<string, string> | undefined,
      onMessage: (msg: BrainStreamMessage) => void,
      onDone: (data: SkillResultData | null) => void,
      onError: (err: string) => void,
      signal?: AbortSignal,
      // #11 SSE 重连参数
      maxRetries?: number,
      onReconnect?: (attempt: number) => void,
      conversationId?: string,
      llmModel?: string,
    ): Promise<void> => {
      const url = `${API_BASE}/agent/skills/run/stream`;
      const body = JSON.stringify({ skill_id: skillId, prompt, params, global_params: globalParams, conversation_id: conversationId || undefined, llm_model: llmModel || undefined });
    let finalData: SkillResultData | null = null;
    let succeeded = false;
    const _maxRetries = maxRetries ?? 0;  // 默认不重连
    let attempt = 0;

    while (!succeeded && attempt <= _maxRetries) {
      try {
        const res = await fetch(url, {
          method: 'POST',
          headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
          body,
          signal,
        });
        if (!res.ok) { onError(`请求失败 (${res.status})`); return; }
        if (!res.body) { onError('响应体为空'); return; }
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        finalData = null;
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n\n');
          buffer = lines.pop() || '';
          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed.startsWith('data:')) continue;
            const payload = trimmed.slice(5).trim();
            if (!payload) continue;
            try {
              const msg = JSON.parse(payload) as BrainStreamMessage;
              if (msg.type === 'error') { onError(msg.content || '执行失败'); return; }
              if (msg.type === 'complete') { finalData = (msg as BrainStreamMessage & { data?: SkillResultData }).data || finalData; onMessage(msg); continue; }
              if (msg.type === 'skill_done') { finalData = (msg as BrainStreamMessage & { data?: SkillResultData }).data || finalData; }
              onMessage(msg);
            } catch { /* ignore */ }
          }
        }
        succeeded = true;
        onDone(finalData);
      } catch (e: any) {
        if (e?.name === 'AbortError') return;
        if (attempt < _maxRetries) {
          attempt++;
          onReconnect?.(attempt);
          const delay = 1000 * Math.pow(2, attempt - 1);
          await new Promise(r => setTimeout(r, delay));
          continue;
        }
        onError(e?.message || 'SSE 连接异常');
        return;
      }
    }
  },
  runPlatformBrain: (prompt: string, globalParams?: Record<string, string>) =>
    request<{ status: string; decision: string; reasoning: string; data: SkillResultData; results: SkillResultData[]; short_drama_params?: Record<string, unknown> }>('/agent/platform/run', {
      method: 'POST',
      body: JSON.stringify({ prompt, global_params: globalParams }),
    }),
  runPlatformBrainStream: async (
    prompt: string,
    globalParams: Record<string, string> | undefined,
    onMessage: (msg: BrainStreamMessage) => void,
    onDone: (result: PlatformBrainResult | null) => void,
    onError: (err: string) => void,
    signal?: AbortSignal,
    // #11 SSE 重连参数
    maxRetries?: number,
    onReconnect?: (attempt: number) => void,
  ): Promise<void> => {
    const url = `${API_BASE}/agent/platform/run/stream`;
    const body = JSON.stringify({ prompt, global_params: globalParams });
    let finalResult: PlatformBrainResult | null = null;
    let succeeded = false;
    const _maxRetries = maxRetries ?? 0;  // 默认不重连
    let attempt = 0;

    while (!succeeded && attempt <= _maxRetries) {
      try {
        const res = await fetch(url, {
          method: 'POST',
          headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
          body,
          signal,
        });
        if (!res.ok) { onError(`请求失败 (${res.status})`); return; }
        if (!res.body) { onError('响应体为空'); return; }
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        finalResult = null;
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n\n');
          buffer = lines.pop() || '';
          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed.startsWith('data:')) continue;
            const payload = trimmed.slice(5).trim();
            if (!payload) continue;
            try {
              const msg = JSON.parse(payload) as BrainStreamMessage;
              if (msg.type === 'error') { onError(msg.content || '执行失败'); return; }
              if (msg.type === 'complete') {
                finalResult = {
                  decision: (msg as BrainStreamMessage & { decision?: string }).decision,
                  data: (msg as BrainStreamMessage & { data?: SkillResultData }).data,
                  results: (msg as BrainStreamMessage & { results?: SkillResultData[] }).results,
                  short_drama_params: (msg as BrainStreamMessage & { short_drama_params?: Record<string, unknown> }).short_drama_params,
                };
              }
              if (msg.type === 'skill_done') {
                finalResult = finalResult || {};
                finalResult.data = (msg as BrainStreamMessage & { data?: SkillResultData }).data;
              }
              onMessage(msg);
            } catch { /* ignore */ }
          }
        }
        succeeded = true;
        onDone(finalResult);
      } catch (e: any) {
        if (e?.name === 'AbortError') return;
        if (attempt < _maxRetries) {
          attempt++;
          onReconnect?.(attempt);
          const delay = 1000 * Math.pow(2, attempt - 1);
          await new Promise(r => setTimeout(r, delay));
          continue;
        }
        onError(e?.message || 'SSE 连接异常');
        return;
      }
    }
  },

  // Admin
  adminStats: () => request<AdminStats>('/admin/stats'),
  adminListUsers: (q?: string, limit?: number, offset?: number) => {
    const params = new URLSearchParams();
    if (q) params.append('q', q);
    if (limit) params.append('limit', String(limit));
    if (offset !== undefined) params.append('offset', String(offset));
    const query = params.toString() ? `?${params.toString()}` : '';
    return request<{ total: number; items: AdminUser[] }>(`/admin/users${query}`);
  },
  adminUpdateUser: (userId: string, data: {
    credits_delta?: number;
    is_admin?: boolean;
    is_active?: boolean;
    new_password?: string;
    note?: string;
  }) =>
    request<AdminUser>(`/admin/users/${userId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  adminDeleteUser: (userId: string) => request(`/admin/users/${userId}`, { method: 'DELETE' }),
  adminListRedeemCodes: (batchId?: string, used?: boolean, limit?: number, offset?: number) => {
    const params = new URLSearchParams();
    if (batchId) params.append('batch_id', batchId);
    if (used !== undefined) params.append('used', String(used));
    if (limit) params.append('limit', String(limit));
    if (offset !== undefined) params.append('offset', String(offset));
    const query = params.toString() ? `?${params.toString()}` : '';
    return request<RedeemCodeList>(`/admin/redeem-codes${query}`);
  },
  adminCreateRedeemCodes: (data: {
    points: number;
    count: number;
    batch_id?: string;
    note?: string;
    expires_days?: number;
  }) =>
    request<{ codes: string[]; count: number; points: number; batch_id: string | null }>(
      '/admin/redeem-codes',
      { method: 'POST', body: JSON.stringify(data) }
    ),
  adminListRechargeTiers: () => request<RechargeTier[]>('/admin/recharge-tiers'),
  adminCreateRechargeTier: (data: { yuan: number; credits: number; enabled?: boolean; order?: number }) =>
    request<RechargeTier>('/admin/recharge-tiers', { method: 'POST', body: JSON.stringify(data) }),
  adminUpdateRechargeTier: (id: string, data: { yuan: number; credits: number; enabled?: boolean; order?: number }) =>
    request<RechargeTier>(`/admin/recharge-tiers/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  adminDeleteRechargeTier: (id: string) => request(`/admin/recharge-tiers/${id}`, { method: 'DELETE' }),
  adminListModelConfigs: (type?: string) => {
    const params = new URLSearchParams();
    if (type) params.append('type', type);
    const query = params.toString() ? `?${params.toString()}` : '';
    return request<ModelConfig[]>(`/admin/model-configs${query}`);
  },
  adminUpdateModelConfig: (id: string, data: {
    name?: string;
    description?: string;
    enabled?: boolean;
    order?: number;
    credits?: number;
    credits_5s?: number;
    credits_10s?: number;
    credits_15s?: number;
  }) =>
    request<ModelConfig>(`/admin/model-configs/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  adminCreateModelConfig: (data: {
    model_id: string;
    name: string;
    type: 'image' | 'video' | 'audio' | 'llm';
    description?: string;
    enabled?: boolean;
    order?: number;
    credits?: number;
    credits_5s?: number;
    credits_10s?: number;
    credits_15s?: number;
  }) =>
    request<ModelConfig>('/admin/model-configs', { method: 'POST', body: JSON.stringify(data) }),
  adminListAnnouncements: (limit?: number, offset?: number) => {
    const params = new URLSearchParams();
    if (limit) params.append('limit', String(limit));
    if (offset !== undefined) params.append('offset', String(offset));
    const query = params.toString() ? `?${params.toString()}` : '';
    return request<AnnouncementList>(`/admin/announcements${query}`);
  },
  adminCreateAnnouncement: (data: {
    title: string;
    content: string;
    type?: string;
    pinned?: boolean;
    enabled?: boolean;
  }) =>
    request<Announcement>('/admin/announcements', { method: 'POST', body: JSON.stringify(data) }),
  adminUpdateAnnouncement: (id: string, data: Partial<{
    title: string;
    content: string;
    type: string;
    pinned: boolean;
    enabled: boolean;
  }>) =>
    request<Announcement>(`/admin/announcements/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  adminDeleteAnnouncement: (id: string) => request(`/admin/announcements/${id}`, { method: 'DELETE' }),
  adminListOrders: (status?: string, channel?: string, limit?: number, offset?: number) => {
    const params = new URLSearchParams();
    if (status) params.append('status', status);
    if (channel) params.append('channel', channel);
    if (limit) params.append('limit', String(limit));
    if (offset !== undefined) params.append('offset', String(offset));
    const query = params.toString() ? `?${params.toString()}` : '';
    return request<AdminOrderList>(`/admin/orders${query}`);
  },
  adminListLedger: (userId?: string, reason?: string, limit?: number, offset?: number) => {
    const params = new URLSearchParams();
    if (userId) params.append('user_id', userId);
    if (reason) params.append('reason', reason);
    if (limit) params.append('limit', String(limit));
    if (offset !== undefined) params.append('offset', String(offset));
    const query = params.toString() ? `?${params.toString()}` : '';
    return request<AdminLedgerList>(`/admin/credits/ledger${query}`);
  },
};

// ─── Skill Conversations ────────────────────────────────

export interface SkillConversationItem {
  id: string;
  skill_id: string;
  skill_title: string | null;
  title: string | null;
  params: Record<string, unknown> | null;
  message_count: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface SkillMessageItem {
  id: string;
  role: string;
  content: string;
  raw_data: Record<string, unknown> | null;
  params_used: Record<string, unknown> | null;
  created_at: string | null;
}

export interface SkillConversationDetail extends SkillConversationItem {
  messages: SkillMessageItem[];
}

export const skillConversationsApi = {
  list: (skillId?: string, limit = 50, offset = 0) => {
    const params = new URLSearchParams();
    if (skillId) params.append('skill_id', skillId);
    params.append('limit', String(limit));
    params.append('offset', String(offset));
    return request<{ status: string; total: number; conversations: SkillConversationItem[] }>(
      `/skill-conversations?${params.toString()}`
    );
  },
  create: (skillId: string, skillTitle?: string, params?: Record<string, unknown>) =>
    request<{ status: string; conversation: SkillConversationItem }>('/skill-conversations', {
      method: 'POST',
      body: JSON.stringify({ skill_id: skillId, skill_title: skillTitle, params }),
    }),
  get: (conversationId: string) =>
    request<{ status: string; conversation: SkillConversationItem; messages: SkillMessageItem[] }>(
      `/skill-conversations/${conversationId}`
    ),
  appendMessage: (conversationId: string, role: string, content: string, rawData?: Record<string, unknown>, paramsUsed?: Record<string, unknown>) =>
    request<{ status: string; message: SkillMessageItem }>(`/skill-conversations/${conversationId}/messages`, {
      method: 'POST',
      body: JSON.stringify({ role, content, raw_data: rawData, params_used: paramsUsed }),
    }),
  updateTitle: (conversationId: string, title: string) =>
    request<{ status: string; title: string }>(`/skill-conversations/${conversationId}/title`, {
      method: 'PATCH',
      body: JSON.stringify({ title }),
    }),
  delete: (conversationId: string) =>
    request<{ status: string }>(`/skill-conversations/${conversationId}`, { method: 'DELETE' }),
};

import type {
  CanvasListItem, Canvas, CanvasNode, CanvasEdge, TaskInfo,
  AgentSession, LockedAsset, Asset, WorkflowMessage, BrainStreamMessage,
  Team, TeamMember,
} from '@/types';

// ─── Enhanced Feature Types ────────────────────────────────

export interface StyleTemplate {
  id: string;
  name: string;
  description: string | null;
  category: string;
  preview_url: string | null;
}

export interface StyleMetadata {
  art_style: string;
  color_palette: string[];
  camera_style: string;
}

export interface SessionVersion {
  id: string;
  version_number: number;
  created_at: string;
  summary: string | null;
}

export interface NovelImportPlan {
  title: string;
  total_episodes: number;
  episodes: Array<{ episode: number; title: string; summary: string }>;
}

export interface EpisodeScript {
  episode: number;
  title: string;
  content: string;
  scenes: string[];
}

export interface CharacterVerifyInput {
  name: string;
  description: string;
  reference_image_url?: string;
}

export interface CharacterVerifyResult {
  name: string;
  consistent: boolean;
  issues: string[];
  confidence: number;
}

export interface StoryboardPanel {
  index: number;
  description: string;
  prompt: string;
}

export interface CharacterAsset {
  char_id: string;
  name: string;
  image_url: string | null;
}

export interface ConsistencyCheckResult {
  overall_consistent: boolean;
  panel_issues: Array<{ index: number; issues: string[] }>;
}

export interface IpAsset {
  id: string;
  name: string;
  asset_type: string;
  file_url: string;
  style_tag: string | null;
  genre_tag: string | null;
  is_public: boolean;
}

export interface IpAssetCreate {
  name: string;
  asset_type: string;
  file_url: string;
  style_tag?: string;
  genre_tag?: string;
  is_public?: boolean;
}

export interface Collaborator {
  id: string;
  user_id: string;
  username: string;
  role: string;
}

export interface SkillResultData {
  [key: string]: unknown;
}

export interface PlatformBrainResult {
  decision?: string;
  data?: SkillResultData;
  results?: SkillResultData[];
  short_drama_params?: Record<string, unknown>;
}
