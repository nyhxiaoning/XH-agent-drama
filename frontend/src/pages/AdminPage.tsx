import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/store/auth';
import { api } from '@/utils/api';
import type {
  AdminStats, AdminUser, AdminOrder, AdminLedgerEntry,
  RedeemCode, RechargeTier,
  ModelConfig, Announcement
} from '@/utils/api';
import {
  ArrowLeft, LayoutDashboard, Users, Gift, CreditCard,
  Cpu, Megaphone, Loader2, Search, Trash2, Save, Plus,
  Feather, CheckCircle2, AlertCircle, ReceiptText, ScrollText
} from 'lucide-react';

type Tab = 'stats' | 'users' | 'redeem' | 'tiers' | 'models' | 'announcements' | 'orders' | 'ledger';

export default function AdminPage() {
  const navigate = useNavigate();
  const { user } = useAuthStore();
  const [tab, setTab] = useState<Tab>('stats');

  return (
    <div className="min-h-screen bg-canvas-bg text-theme-main animate-fade-in">
      <div className="border-b border-panel-border glass sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-teal-600 to-emerald-700 flex items-center justify-center shadow-glow">
              <Feather size={16} className="text-theme-invert" />
            </div>
            <h1 className="text-xl font-bold text-theme-main flex items-center gap-2">
              <LayoutDashboard className="w-5 h-5 text-accent" />
              管理员后台
            </h1>
          </div>
          <button
            onClick={() => navigate('/profile')}
            className="btn-ghost"
          >
            <ArrowLeft className="w-4 h-4" />
            返回
          </button>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-6 flex gap-6">
        <aside className="w-48 shrink-0 space-y-1">
          <NavItem tab="stats" label="数据统计" icon={<LayoutDashboard className="w-4 h-4" />} active={tab} onClick={setTab} />
          <NavItem tab="users" label="用户管理" icon={<Users className="w-4 h-4" />} active={tab} onClick={setTab} />
          <NavItem tab="redeem" label="兑换码" icon={<Gift className="w-4 h-4" />} active={tab} onClick={setTab} />
          <NavItem tab="tiers" label="充值档位" icon={<CreditCard className="w-4 h-4" />} active={tab} onClick={setTab} />
          <NavItem tab="models" label="模型配置" icon={<Cpu className="w-4 h-4" />} active={tab} onClick={setTab} />
          <NavItem tab="announcements" label="公告管理" icon={<Megaphone className="w-4 h-4" />} active={tab} onClick={setTab} />
          <NavItem tab="orders" label="充值订单" icon={<ReceiptText className="w-4 h-4" />} active={tab} onClick={setTab} />
          <NavItem tab="ledger" label="积分流水" icon={<ScrollText className="w-4 h-4" />} active={tab} onClick={setTab} />
        </aside>

        <main className="flex-1 min-w-0 pb-12">
          {tab === 'stats' && <StatsPanel />}
          {tab === 'users' && <UsersPanel />}
          {tab === 'redeem' && <RedeemPanel />}
          {tab === 'tiers' && <TiersPanel />}
          {tab === 'models' && <ModelsPanel />}
          {tab === 'announcements' && <AnnouncementsPanel />}
          {tab === 'orders' && <OrdersPanel />}
          {tab === 'ledger' && <LedgerPanel />}
        </main>
      </div>
    </div>
  );
}

function NavItem({ tab, label, icon, active, onClick }: {
  tab: Tab; label: string; icon: React.ReactNode; active: Tab; onClick: (t: Tab) => void;
}) {
  return (
    <button
      onClick={() => onClick(tab)}
      className={`w-full flex items-center gap-2 px-3 py-2 rounded-xl text-sm transition-all ${
        active === tab
          ? 'btn-primary justify-start'
          : 'btn-ghost justify-start'
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

function StatsPanel() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.adminStats().then(setStats).catch(() => setStats(null)).finally(() => setLoading(false));
  }, []);

  if (loading) return <PanelLoading />;
  if (!stats) return <div className="text-theme-muted">加载失败</div>;

  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold text-theme-main">平台统计</h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="总用户" value={stats.total_users} />
        <StatCard label="今日活跃" value={stats.today_active_users} />
        <StatCard label="本周活跃" value={stats.week_active_users} />
        <StatCard label="总充值(元)" value={stats.total_recharged_yuan} />
        <StatCard label="今日充值(元)" value={stats.today_recharged_yuan} />
        <StatCard label="本周充值(元)" value={stats.week_recharged_yuan} />
        <StatCard label="图片生成" value={stats.total_images} />
        <StatCard label="视频生成" value={stats.total_videos} />
      </div>

      <div className="card p-6">
        <h3 className="font-medium mb-4 text-theme-main">模型使用排行</h3>
        {stats.model_ranking.length === 0 ? (
          <div className="text-sm text-theme-muted">暂无数据</div>
        ) : (
          <div className="space-y-2">
            {stats.model_ranking.map((m) => (
              <div key={m.model} className="flex items-center justify-between text-sm rounded-xl glass p-3">
                <span className="font-medium truncate text-theme-main">{m.model}</span>
                <span className="text-theme-muted">{m.count} 次</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function UsersPanel() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState('');
  const [offset, setOffset] = useState(0);
  const limit = 20;
  const [loading, setLoading] = useState(false);
  const [actingId, setActingId] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const res = await api.adminListUsers(q, limit, offset);
      setUsers(res.items);
      setTotal(res.total);
    } catch {
      setUsers([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [q, offset]);

  const updateUser = async (id: string, data: Parameters<typeof api.adminUpdateUser>[1]) => {
    setActingId(id);
    try {
      await api.adminUpdateUser(id, data);
      await load();
    } catch (err: any) {
      alert(err.message || '操作失败');
    } finally {
      setActingId(null);
    }
  };

  const deleteUser = async (id: string) => {
    if (!confirm('确定删除该用户？')) return;
    setActingId(id);
    try {
      await api.adminDeleteUser(id);
      await load();
    } catch (err: any) {
      alert(err.message || '删除失败');
    } finally {
      setActingId(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-theme-muted" />
          <input
            value={q}
            onChange={(e) => { setQ(e.target.value); setOffset(0); }}
            placeholder="搜索邮箱/手机/昵称"
            className="input-field pl-9"
          />
        </div>
      </div>

      {loading ? <PanelLoading /> : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-panel-bg text-theme-muted">
              <tr>
                <th className="text-left px-4 py-3 font-medium">用户</th>
                <th className="text-left px-4 py-3 font-medium">积分</th>
                <th className="text-left px-4 py-3 font-medium">身份</th>
                <th className="text-left px-4 py-3 font-medium">状态</th>
                <th className="text-left px-4 py-3 font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-t border-panel-border">
                  <td className="px-4 py-3">
                    <div className="font-medium text-theme-main">{u.name || '未命名'}</div>
                    <div className="text-xs text-theme-muted">{u.email || u.phone}</div>
                  </td>
                  <td className="px-4 py-3 text-theme-main">{u.credits}</td>
                  <td className="px-4 py-3 text-theme-main">{u.is_admin ? '管理员' : '用户'}</td>
                  <td className="px-4 py-3 text-theme-main">{u.is_active ? '正常' : '禁用'}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-2">
                      <button
                        onClick={() => {
                          const delta = prompt('调整积分（正数增加，负数扣减）：');
                          if (!delta) return;
                          const val = Number(delta);
                          if (Number.isNaN(val) || val === 0) {
                            alert('请输入非 0 的有效数字');
                            return;
                          }
                          updateUser(u.id, { credits_delta: val, note: '管理员调整' });
                        }}
                        disabled={actingId === u.id}
                        className="btn-secondary btn-sm disabled:opacity-50"
                      >
                        调积分
                      </button>
                      <button
                        onClick={() => updateUser(u.id, { is_active: !u.is_active })}
                        disabled={actingId === u.id}
                        className="btn-secondary btn-sm disabled:opacity-50"
                      >
                        {u.is_active ? '禁用' : '启用'}
                      </button>
                      <button
                        onClick={() => {
                          if (!confirm(`确定${u.is_admin ? '取消' : '设为'}管理员？`)) return;
                          updateUser(u.id, { is_admin: !u.is_admin });
                        }}
                        disabled={actingId === u.id}
                        className="btn-secondary btn-sm disabled:opacity-50"
                      >
                        {u.is_admin ? '取消管理员' : '设为管理员'}
                      </button>
                      <button
                        onClick={() => {
                          const pwd = prompt('输入新密码（至少6位）：');
                          if (!pwd) return;
                          if (pwd.length < 6) {
                            alert('密码至少 6 位');
                            return;
                          }
                          updateUser(u.id, { new_password: pwd });
                        }}
                        disabled={actingId === u.id}
                        className="btn-secondary btn-sm disabled:opacity-50"
                      >
                        重置密码
                      </button>
                      <button
                        onClick={() => deleteUser(u.id)}
                        disabled={actingId === u.id}
                        className="btn-danger btn-sm disabled:opacity-50"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center justify-between text-sm">
        <button
          disabled={offset === 0}
          onClick={() => setOffset((p) => Math.max(0, p - limit))}
          className="btn-secondary btn-sm disabled:opacity-50"
        >
          上一页
        </button>
        <span className="text-theme-muted">{offset + 1} - {Math.min(offset + limit, total)} / {total}</span>
        <button
          disabled={offset + limit >= total}
          onClick={() => setOffset((p) => p + limit)}
          className="btn-secondary btn-sm disabled:opacity-50"
        >
          下一页
        </button>
      </div>
    </div>
  );
}

function RedeemPanel() {
  const [codes, setCodes] = useState<RedeemCode[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const limit = 20;
  const [points, setPoints] = useState(100);
  const [count, setCount] = useState(10);
  const [batchId, setBatchId] = useState('');
  const [expiresDays, setExpiresDays] = useState('');
  const [generated, setGenerated] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [filterBatch, setFilterBatch] = useState('');
  const [filterUsed, setFilterUsed] = useState<string>('');

  const load = async () => {
    setLoading(true);
    try {
      const used = filterUsed === 'used' ? true : filterUsed === 'unused' ? false : undefined;
      const res = await api.adminListRedeemCodes(filterBatch || undefined, used, limit, offset);
      setCodes(res.items);
      setTotal(res.total);
    } catch {
      setCodes([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [offset, filterBatch, filterUsed]);

  const create = async () => {
    if (count <= 0 || points <= 0) {
      alert('积分和数量必须大于 0');
      return;
    }
    setGenerating(true);
    try {
      const expires = expiresDays.trim() ? Number(expiresDays) : undefined;
      const res = await api.adminCreateRedeemCodes({
        points, count,
        batch_id: batchId || undefined,
        expires_days: expires && !Number.isNaN(expires) && expires > 0 ? expires : undefined,
      });
      setGenerated(res.codes);
      setOffset(0);
      await load();
    } catch (err: any) {
      alert(err.message || '生成失败');
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="card p-6">
        <h3 className="font-medium mb-4 text-theme-main">批量生成兑换码</h3>
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 mb-3">
          <input type="number" value={points} onChange={(e) => setPoints(Number(e.target.value))} placeholder="积分" className="input-field" />
          <input type="number" value={count} onChange={(e) => setCount(Number(e.target.value))} placeholder="数量" className="input-field" />
          <input value={batchId} onChange={(e) => setBatchId(e.target.value)} placeholder="批次 ID（可选）" className="input-field" />
          <input type="number" value={expiresDays} onChange={(e) => setExpiresDays(e.target.value)} placeholder="过期天数（可选）" className="input-field" />
        </div>
        <button
          onClick={create}
          disabled={generating}
          className="btn-primary disabled:opacity-60"
        >
          {generating && <Loader2 className="w-4 h-4 animate-spin" />}
          生成
        </button>
        {generated.length > 0 && (
          <div className="mt-4 rounded-xl glass p-3">
            <div className="text-xs text-theme-muted mb-2">已生成 {generated.length} 个</div>
            <div className="space-y-1 max-h-40 overflow-auto text-xs font-mono text-theme-main">
              {generated.map((c) => <div key={c}>{c}</div>)}
            </div>
          </div>
        )}
      </div>

      <div className="flex gap-3">
        <input
          value={filterBatch}
          onChange={(e) => { setFilterBatch(e.target.value); setOffset(0); }}
          placeholder="按批次筛选"
          className="input-field flex-1"
        />
        <select
          value={filterUsed}
          onChange={(e) => { setFilterUsed(e.target.value); setOffset(0); }}
          className="input-field w-32"
        >
          <option value="">全部</option>
          <option value="unused">未使用</option>
          <option value="used">已使用</option>
        </select>
      </div>

      {loading ? <PanelLoading /> : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-panel-bg text-theme-muted"><tr><th className="text-left px-4 py-3 font-medium">兑换码</th><th className="text-left px-4 py-3 font-medium">积分</th><th className="text-left px-4 py-3 font-medium">批次</th><th className="text-left px-4 py-3 font-medium">过期</th><th className="text-left px-4 py-3 font-medium">状态</th></tr></thead>
            <tbody>
              {codes.map((c) => (
                <tr key={c.id} className="border-t border-panel-border">
                  <td className="px-4 py-3 font-mono text-theme-main">{c.code}</td>
                  <td className="px-4 py-3 text-theme-main">{c.points}</td>
                  <td className="px-4 py-3 text-theme-muted">{c.batch_id || '-'}</td>
                  <td className="px-4 py-3 text-theme-muted">{c.expires_at ? new Date(c.expires_at).toLocaleDateString() : '永久'}</td>
                  <td className="px-4 py-3 text-theme-muted">{c.used_at ? `已用 ${new Date(c.used_at).toLocaleDateString()}` : '未使用'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center justify-between text-sm">
        <button
          disabled={offset === 0}
          onClick={() => setOffset((p) => Math.max(0, p - limit))}
          className="btn-secondary btn-sm disabled:opacity-50"
        >
          上一页
        </button>
        <span className="text-theme-muted">{offset + 1} - {Math.min(offset + limit, total)} / {total}</span>
        <button
          disabled={offset + limit >= total}
          onClick={() => setOffset((p) => p + limit)}
          className="btn-secondary btn-sm disabled:opacity-50"
        >
          下一页
        </button>
      </div>
    </div>
  );
}

function TiersPanel() {
  const [tiers, setTiers] = useState<RechargeTier[]>([]);
  const [yuan, setYuan] = useState(10);
  const [credits, setCredits] = useState(1000);
  const [editing, setEditing] = useState<RechargeTier | null>(null);
  const [editEnabled, setEditEnabled] = useState(true);
  const [editOrder, setEditOrder] = useState(0);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const load = async () => {
    const res = await api.adminListRechargeTiers().catch(() => []);
    setTiers(res);
  };

  useEffect(() => { load(); }, []);

  const save = async () => {
    if (yuan <= 0 || credits <= 0) {
      alert('金额和积分必须大于 0');
      return;
    }
    setSaving(true);
    try {
      if (editing) {
        await api.adminUpdateRechargeTier(editing.id, { yuan, credits, enabled: editEnabled, order: editOrder });
      } else {
        await api.adminCreateRechargeTier({ yuan, credits, enabled: true, order: 0 });
      }
      setEditing(null);
      setEditEnabled(true);
      setEditOrder(0);
      setYuan(10);
      setCredits(1000);
      await load();
    } catch (err: any) {
      alert(err.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const del = async (id: string) => {
    if (!confirm('确定删除？')) return;
    setDeletingId(id);
    try {
      await api.adminDeleteRechargeTier(id);
      await load();
    } catch (err: any) {
      alert(err.message || '删除失败');
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="card p-6">
        <h3 className="font-medium mb-4 text-theme-main">{editing ? '编辑档位' : '新增档位'}</h3>
        <div className="flex flex-wrap gap-3 mb-3 items-center">
          <input type="number" value={yuan} onChange={(e) => setYuan(Number(e.target.value))} placeholder="人民币" className="input-field w-32" />
          <input type="number" value={credits} onChange={(e) => setCredits(Number(e.target.value))} placeholder="积分" className="input-field w-32" />
          {editing && (
            <>
              <label className="flex items-center gap-1.5 text-sm text-theme-sub">
                <input type="checkbox" checked={editEnabled} onChange={(e) => setEditEnabled(e.target.checked)} />
                启用
              </label>
              <input type="number" value={editOrder} onChange={(e) => setEditOrder(Number(e.target.value))} placeholder="排序" className="input-field w-24" />
            </>
          )}
          <button onClick={save} disabled={saving} className="btn-primary disabled:opacity-60">
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            保存
          </button>
          {editing && (
            <button onClick={() => { setEditing(null); setEditEnabled(true); setEditOrder(0); setYuan(10); setCredits(1000); }} className="btn-secondary">
              取消
            </button>
          )}
        </div>
      </div>

      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-panel-bg text-theme-muted"><tr><th className="text-left px-4 py-3 font-medium">金额</th><th className="text-left px-4 py-3 font-medium">积分</th><th className="text-left px-4 py-3 font-medium">状态</th><th className="text-left px-4 py-3 font-medium">操作</th></tr></thead>
          <tbody>
            {tiers.map((t) => (
              <tr key={t.id} className="border-t border-panel-border">
                <td className="px-4 py-3 text-theme-main">¥{t.yuan}</td>
                <td className="px-4 py-3 text-theme-main">{t.credits}</td>
                <td className="px-4 py-3 text-theme-main">{t.enabled ? '启用' : '禁用'}</td>
                <td className="px-4 py-3">
                  <div className="flex gap-2">
                    <button onClick={() => { setEditing(t); setYuan(t.yuan); setCredits(t.credits); setEditEnabled(t.enabled); setEditOrder(t.order); }} className="btn-ghost btn-sm">编辑</button>
                    <button
                      onClick={() => del(t.id)}
                      disabled={deletingId === t.id}
                      className="btn-danger btn-sm disabled:opacity-50"
                    >
                      {deletingId === t.id ? '删除中...' : '删除'}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ModelsPanel() {
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [draftCredits, setDraftCredits] = useState<Record<string, { credits: string; credits_5s: string; credits_10s: string; credits_15s: string }>>({});
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({
    model_id: '',
    name: '',
    type: 'llm' as 'image' | 'video' | 'audio' | 'llm',
    description: '',
    credits: '0',
    credits_5s: '0',
    credits_10s: '0',
    credits_15s: '0',
    order: '0',
    enabled: true,
  });

  const load = async () => {
    setLoading(true);
    try {
      const res = await api.adminListModelConfigs();
      setModels(res);
      const drafts: Record<string, { credits: string; credits_5s: string; credits_10s: string; credits_15s: string }> = {};
      res.forEach((m) => {
        drafts[m.id] = {
          credits: String(m.credits),
          credits_5s: String(m.credits_5s ?? 0),
          credits_10s: String(m.credits_10s ?? 0),
          credits_15s: String(m.credits_15s ?? 0),
        };
      });
      setDraftCredits(drafts);
    } catch {
      setModels([]);
      setDraftCredits({});
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const update = async (m: ModelConfig, patch: Partial<ModelConfig>) => {
    setUpdatingId(m.id);
    try {
      await api.adminUpdateModelConfig(m.id, patch);
      await load();
    } catch (err: any) {
      alert(err.message || '更新失败');
    } finally {
      setUpdatingId(null);
    }
  };

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    const credits = Number(form.credits);
    const order = Number(form.order);
    if (!form.model_id.trim() || !form.name.trim()) {
      alert('model_id 和 模型名称 不能为空');
      return;
    }
    setCreating(true);
    try {
      await api.adminCreateModelConfig({
        model_id: form.model_id.trim(),
        name: form.name.trim(),
        type: form.type,
        description: form.description.trim() || undefined,
        credits: Number.isNaN(credits) || credits < 0 ? 0 : credits,
        credits_5s: form.type === 'video' ? (Number(form.credits_5s) || 0) : 0,
        credits_10s: form.type === 'video' ? (Number(form.credits_10s) || 0) : 0,
        credits_15s: form.type === 'video' ? (Number(form.credits_15s) || 0) : 0,
        order: Number.isNaN(order) ? 0 : order,
        enabled: form.enabled,
      });
      setForm({ model_id: '', name: '', type: 'llm', description: '', credits: '0', credits_5s: '0', credits_10s: '0', credits_15s: '0', order: '0', enabled: true });
      setShowCreate(false);
      await load();
    } catch (err: any) {
      alert(err.message || '添加失败');
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-theme-sub">图片/视频/语言模型配置</h3>
        <button
          onClick={() => setShowCreate((v) => !v)}
          className="btn-primary text-xs px-3 py-1.5 flex items-center gap-1"
        >
          <Plus size={14} />
          {showCreate ? '取消' : '添加模型'}
        </button>
      </div>

      {showCreate && (
        <form onSubmit={create} className="card p-4 space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-xs text-theme-muted">model_id <span className="text-error">*</span></label>
              <input
                type="text"
                value={form.model_id}
                onChange={(e) => setForm((f) => ({ ...f, model_id: e.target.value }))}
                placeholder="如 doubao-pro-256k"
                className="input-field w-full text-xs py-1.5"
                disabled={creating}
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-theme-muted">模型名称 <span className="text-error">*</span></label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="如 豆包 Pro"
                className="input-field w-full text-xs py-1.5"
                disabled={creating}
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-theme-muted">类型</label>
              <select
                value={form.type}
                onChange={(e) => setForm((f) => ({ ...f, type: e.target.value as typeof form.type }))}
                className="input-field w-full text-xs py-1.5"
                disabled={creating}
              >
                <option value="llm">llm</option>
                <option value="image">image</option>
                <option value="video">video</option>
                <option value="audio">audio</option>
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-theme-muted">描述</label>
              <input
                type="text"
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                placeholder="可选"
                className="input-field w-full text-xs py-1.5"
                disabled={creating}
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-theme-muted">{form.type === 'video' ? '积分（按秒，兼容旧逻辑）' : '积分'}</label>
              <input
                type="number"
                min={0}
                value={form.credits}
                onChange={(e) => setForm((f) => ({ ...f, credits: e.target.value }))}
                className="input-field w-full text-xs py-1.5"
                disabled={creating}
              />
            </div>
            {form.type === 'video' && (
              <>
                <div className="space-y-1">
                  <label className="text-xs text-theme-muted">5秒积分</label>
                  <input
                    type="number"
                    min={0}
                    value={form.credits_5s}
                    onChange={(e) => setForm((f) => ({ ...f, credits_5s: e.target.value }))}
                    className="input-field w-full text-xs py-1.5"
                    disabled={creating}
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-theme-muted">10秒积分</label>
                  <input
                    type="number"
                    min={0}
                    value={form.credits_10s}
                    onChange={(e) => setForm((f) => ({ ...f, credits_10s: e.target.value }))}
                    className="input-field w-full text-xs py-1.5"
                    disabled={creating}
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-theme-muted">15秒积分</label>
                  <input
                    type="number"
                    min={0}
                    value={form.credits_15s}
                    onChange={(e) => setForm((f) => ({ ...f, credits_15s: e.target.value }))}
                    className="input-field w-full text-xs py-1.5"
                    disabled={creating}
                  />
                </div>
              </>
            )}
            <div className="space-y-1">
              <label className="text-xs text-theme-muted">排序</label>
              <input
                type="number"
                value={form.order}
                onChange={(e) => setForm((f) => ({ ...f, order: e.target.value }))}
                className="input-field w-full text-xs py-1.5"
                disabled={creating}
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <input
              id="model-enabled"
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
              disabled={creating}
            />
            <label htmlFor="model-enabled" className="text-xs text-theme-sub cursor-pointer">立即启用</label>
          </div>
          <div className="flex justify-end">
            <button type="submit" disabled={creating} className="btn-primary text-xs px-4 py-1.5 flex items-center gap-1">
              {creating ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              保存
            </button>
          </div>
        </form>
      )}

      {loading ? <PanelLoading /> : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-panel-bg text-theme-muted"><tr><th className="text-left px-4 py-3 font-medium">模型</th><th className="text-left px-4 py-3 font-medium">类型</th><th className="text-left px-4 py-3 font-medium">积分</th><th className="text-left px-4 py-3 font-medium">启用</th></tr></thead>
            <tbody>
              {models.map((m) => {
                const d = draftCredits[m.id] || { credits: String(m.credits), credits_5s: String(m.credits_5s ?? 0), credits_10s: String(m.credits_10s ?? 0), credits_15s: String(m.credits_15s ?? 0) };
                const isVideo = m.type === 'video';
                return (
                <tr key={m.id} className="border-t border-panel-border">
                  <td className="px-4 py-3">
                    <div className="font-medium text-theme-main">{m.name}</div>
                    <div className="text-xs text-theme-muted font-mono">{m.model_id}</div>
                  </td>
                  <td className="px-4 py-3 text-theme-muted">{m.type}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="flex items-center gap-1">
                        <span className="text-[10px] text-theme-hint shrink-0">{isVideo ? '按秒' : '积分'}</span>
                        <input
                          type="number"
                          value={d.credits}
                          disabled={updatingId === m.id}
                          onChange={(e) => setDraftCredits((prev) => ({ ...prev, [m.id]: { ...d, credits: e.target.value } }))}
                          onBlur={() => {
                            const val = Number(d.credits);
                            if (!Number.isNaN(val) && val >= 0 && val !== m.credits) {
                              update(m, { credits: val });
                            }
                          }}
                          className="input-field w-16 py-1 text-xs disabled:opacity-50"
                        />
                      </div>
                      {isVideo && (
                        <>
                          <div className="flex items-center gap-1">
                            <span className="text-[10px] text-theme-hint shrink-0">5s</span>
                            <input
                              type="number"
                              value={d.credits_5s}
                              disabled={updatingId === m.id}
                              onChange={(e) => setDraftCredits((prev) => ({ ...prev, [m.id]: { ...d, credits_5s: e.target.value } }))}
                              onBlur={() => {
                                const val = Number(d.credits_5s);
                                if (!Number.isNaN(val) && val >= 0 && val !== (m.credits_5s ?? 0)) {
                                  update(m, { credits_5s: val });
                                }
                              }}
                              className="input-field w-16 py-1 text-xs disabled:opacity-50"
                            />
                          </div>
                          <div className="flex items-center gap-1">
                            <span className="text-[10px] text-theme-hint shrink-0">10s</span>
                            <input
                              type="number"
                              value={d.credits_10s}
                              disabled={updatingId === m.id}
                              onChange={(e) => setDraftCredits((prev) => ({ ...prev, [m.id]: { ...d, credits_10s: e.target.value } }))}
                              onBlur={() => {
                                const val = Number(d.credits_10s);
                                if (!Number.isNaN(val) && val >= 0 && val !== (m.credits_10s ?? 0)) {
                                  update(m, { credits_10s: val });
                                }
                              }}
                              className="input-field w-16 py-1 text-xs disabled:opacity-50"
                            />
                          </div>
                          <div className="flex items-center gap-1">
                            <span className="text-[10px] text-theme-hint shrink-0">15s</span>
                            <input
                              type="number"
                              value={d.credits_15s}
                              disabled={updatingId === m.id}
                              onChange={(e) => setDraftCredits((prev) => ({ ...prev, [m.id]: { ...d, credits_15s: e.target.value } }))}
                              onBlur={() => {
                                const val = Number(d.credits_15s);
                                if (!Number.isNaN(val) && val >= 0 && val !== (m.credits_15s ?? 0)) {
                                  update(m, { credits_15s: val });
                                }
                              }}
                              className="input-field w-16 py-1 text-xs disabled:opacity-50"
                            />
                          </div>
                        </>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <label className={`inline-flex items-center gap-2 cursor-pointer ${updatingId === m.id ? 'opacity-50' : ''}`} style={{ pointerEvents: updatingId === m.id ? 'none' : undefined }}>
                      <input
                        type="checkbox"
                        checked={m.enabled}
                        disabled={updatingId === m.id}
                        onChange={(e) => update(m, { enabled: e.target.checked })}
                      />
                      <span className="text-xs text-theme-muted">{m.enabled ? '启用' : '禁用'}</span>
                    </label>
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function AnnouncementsPanel() {
  const [list, setList] = useState<Announcement[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const limit = 20;
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [type, setType] = useState('info');
  const [pinned, setPinned] = useState(false);
  const [editing, setEditing] = useState<Announcement | null>(null);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const load = async () => {
    try {
      const res = await api.adminListAnnouncements(limit, offset);
      setList(res.items);
      setTotal(res.total);
    } catch {
      setList([]);
    }
  };

  useEffect(() => { load(); }, [offset]);

  const save = async () => {
    if (!title.trim() || !content.trim()) {
      alert('标题和内容不能为空');
      return;
    }
    setSaving(true);
    try {
      if (editing) {
        await api.adminUpdateAnnouncement(editing.id, { title, content, type, pinned });
      } else {
        await api.adminCreateAnnouncement({ title, content, type, pinned });
      }
      setEditing(null);
      setTitle('');
      setContent('');
      setType('info');
      setPinned(false);
      setOffset(0);
      await load();
    } catch (err: any) {
      alert(err.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const del = async (id: string) => {
    if (!confirm('确定删除？')) return;
    setDeletingId(id);
    try {
      await api.adminDeleteAnnouncement(id);
      await load();
    } catch (err: any) {
      alert(err.message || '删除失败');
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="card p-6">
        <h3 className="font-medium mb-4 text-theme-main">{editing ? '编辑公告' : '发布公告'}</h3>
        <div className="space-y-3">
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="标题" className="input-field" />
          <textarea value={content} onChange={(e) => setContent(e.target.value)} placeholder="内容（支持 Markdown）" rows={4} className="input-field min-h-[100px]" />
          <div className="flex flex-wrap gap-3">
            <select value={type} onChange={(e) => setType(e.target.value)} className="input-field w-auto">
              <option value="info">info</option>
              <option value="success">success</option>
              <option value="warning">warning</option>
              <option value="danger">danger</option>
            </select>
            <label className="flex items-center gap-1.5 text-sm text-theme-sub">
              <input type="checkbox" checked={pinned} onChange={(e) => setPinned(e.target.checked)} />
              置顶
            </label>
          </div>
          <div className="flex gap-2">
            <button onClick={save} disabled={saving} className="btn-primary disabled:opacity-60">
              {saving && <Loader2 className="w-4 h-4 animate-spin" />}
              保存
            </button>
            {editing && (
              <button onClick={() => { setEditing(null); setTitle(''); setContent(''); setType('info'); setPinned(false); }} className="btn-secondary">取消</button>
            )}
          </div>
        </div>
      </div>

      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-panel-bg text-theme-muted"><tr><th className="text-left px-4 py-3 font-medium">标题</th><th className="text-left px-4 py-3 font-medium">类型</th><th className="text-left px-4 py-3 font-medium">状态</th><th className="text-left px-4 py-3 font-medium">操作</th></tr></thead>
          <tbody>
            {list.map((a) => (
              <tr key={a.id} className="border-t border-panel-border">
                <td className="px-4 py-3 text-theme-main">{a.title}</td>
                <td className="px-4 py-3 text-theme-muted">{a.type}</td>
                <td className="px-4 py-3 text-theme-main">{a.enabled ? '启用' : '禁用'}</td>
                <td className="px-4 py-3">
                  <div className="flex gap-2">
                    <button onClick={() => { setEditing(a); setTitle(a.title); setContent(a.content); setType(a.type); setPinned(a.pinned); }} className="btn-ghost btn-sm">编辑</button>
                    <button
                      onClick={async () => {
                        try {
                          await api.adminUpdateAnnouncement(a.id, { enabled: !a.enabled });
                          await load();
                        } catch (err: any) {
                          alert(err.message || '操作失败');
                        }
                      }}
                      className="btn-secondary btn-sm"
                    >
                      {a.enabled ? '禁用' : '启用'}
                    </button>
                    <button onClick={() => del(a.id)} disabled={deletingId === a.id} className="btn-danger btn-sm disabled:opacity-50">
                      {deletingId === a.id ? '删除中...' : '删除'}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between text-sm">
        <button
          disabled={offset === 0}
          onClick={() => setOffset((p) => Math.max(0, p - limit))}
          className="btn-secondary btn-sm disabled:opacity-50"
        >
          上一页
        </button>
        <span className="text-theme-muted">{offset + 1} - {Math.min(offset + limit, total)} / {total}</span>
        <button
          disabled={offset + limit >= total}
          onClick={() => setOffset((p) => p + limit)}
          className="btn-secondary btn-sm disabled:opacity-50"
        >
          下一页
        </button>
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="card p-4 hover:-translate-y-0.5 hover:shadow-soft-lg transition-all">
      <div className="text-2xl font-bold text-theme-main">{value}</div>
      <div className="text-xs text-theme-muted">{label}</div>
    </div>
  );
}

function OrdersPanel() {
  const [orders, setOrders] = useState<AdminOrder[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const limit = 20;
  const [filterStatus, setFilterStatus] = useState('');
  const [filterChannel, setFilterChannel] = useState('');
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await api.adminListOrders(
        filterStatus || undefined,
        filterChannel || undefined,
        limit, offset,
      );
      setOrders(res.items);
      setTotal(res.total);
    } catch {
      setOrders([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [offset, filterStatus, filterChannel]);

  return (
    <div className="space-y-4">
      <div className="flex gap-3">
        <select value={filterStatus} onChange={(e) => { setFilterStatus(e.target.value); setOffset(0); }} className="input-field w-32">
          <option value="">全部状态</option>
          <option value="pending">待支付</option>
          <option value="paid">已支付</option>
          <option value="closed">已关闭</option>
        </select>
        <select value={filterChannel} onChange={(e) => { setFilterChannel(e.target.value); setOffset(0); }} className="input-field w-32">
          <option value="">全部渠道</option>
          <option value="alipay">支付宝</option>
          <option value="wechat">微信</option>
        </select>
      </div>

      {loading ? <PanelLoading /> : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-panel-bg text-theme-muted">
              <tr>
                <th className="text-left px-4 py-3 font-medium">订单号</th>
                <th className="text-left px-4 py-3 font-medium">渠道</th>
                <th className="text-left px-4 py-3 font-medium">金额</th>
                <th className="text-left px-4 py-3 font-medium">积分</th>
                <th className="text-left px-4 py-3 font-medium">状态</th>
                <th className="text-left px-4 py-3 font-medium">时间</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id} className="border-t border-panel-border">
                  <td className="px-4 py-3 font-mono text-xs text-theme-main">{o.out_trade_no}</td>
                  <td className="px-4 py-3 text-theme-muted">{o.channel === 'alipay' ? '支付宝' : '微信'}</td>
                  <td className="px-4 py-3 text-theme-main">¥{o.amount_yuan}</td>
                  <td className="px-4 py-3 text-theme-main">{o.credits}</td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded text-xs ${o.status === 'paid' ? 'bg-green-500/20 text-green-400' : o.status === 'pending' ? 'bg-yellow-500/20 text-yellow-400' : 'bg-gray-500/20 text-gray-400'}`}>
                      {o.status === 'paid' ? '已支付' : o.status === 'pending' ? '待支付' : '已关闭'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-theme-muted">
                    {o.paid_at ? new Date(o.paid_at).toLocaleString() : new Date(o.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center justify-between text-sm">
        <button
          disabled={offset === 0}
          onClick={() => setOffset((p) => Math.max(0, p - limit))}
          className="btn-secondary btn-sm disabled:opacity-50"
        >
          上一页
        </button>
        <span className="text-theme-muted">{offset + 1} - {Math.min(offset + limit, total)} / {total}</span>
        <button
          disabled={offset + limit >= total}
          onClick={() => setOffset((p) => p + limit)}
          className="btn-secondary btn-sm disabled:opacity-50"
        >
          下一页
        </button>
      </div>
    </div>
  );
}

function LedgerPanel() {
  const [entries, setEntries] = useState<AdminLedgerEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const limit = 50;
  const [filterUserId, setFilterUserId] = useState('');
  const [filterReason, setFilterReason] = useState('');
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await api.adminListLedger(
        filterUserId || undefined,
        filterReason || undefined,
        limit, offset,
      );
      setEntries(res.items);
      setTotal(res.total);
    } catch {
      setEntries([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [offset, filterUserId, filterReason]);

  return (
    <div className="space-y-4">
      <div className="flex gap-3">
        <input
          value={filterUserId}
          onChange={(e) => { setFilterUserId(e.target.value); setOffset(0); }}
          placeholder="按用户 ID 筛选"
          className="input-field flex-1"
        />
        <select value={filterReason} onChange={(e) => { setFilterReason(e.target.value); setOffset(0); }} className="input-field w-40">
          <option value="">全部原因</option>
          <option value="generate_image">生图</option>
          <option value="generate_video">生视频</option>
          <option value="generate_audio">生音频</option>
          <option value="batch_generate">批量生成</option>
          <option value="generate_image_refund">生图退款</option>
          <option value="generate_video_refund">生视频退款</option>
          <option value="admin_adjust">管理员调整</option>
          <option value="redeem">兑换码</option>
          <option value="alipay_recharge">支付宝充值</option>
          <option value="wechat_recharge">微信充值</option>
        </select>
      </div>

      {loading ? <PanelLoading /> : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-panel-bg text-theme-muted">
              <tr>
                <th className="text-left px-4 py-3 font-medium">时间</th>
                <th className="text-left px-4 py-3 font-medium">用户</th>
                <th className="text-left px-4 py-3 font-medium">变动</th>
                <th className="text-left px-4 py-3 font-medium">余额</th>
                <th className="text-left px-4 py-3 font-medium">原因</th>
                <th className="text-left px-4 py-3 font-medium">描述</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id} className="border-t border-panel-border">
                  <td className="px-4 py-3 text-xs text-theme-muted">{new Date(e.created_at).toLocaleString()}</td>
                  <td className="px-4 py-3 font-mono text-xs text-theme-muted">{e.user_id.slice(0, 8)}...</td>
                  <td className={`px-4 py-3 font-medium ${e.amount > 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {e.amount > 0 ? '+' : ''}{e.amount}
                  </td>
                  <td className="px-4 py-3 text-theme-main">{e.balance_after}</td>
                  <td className="px-4 py-3 text-theme-muted">{e.reason}</td>
                  <td className="px-4 py-3 text-xs text-theme-muted">{e.description || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center justify-between text-sm">
        <button
          disabled={offset === 0}
          onClick={() => setOffset((p) => Math.max(0, p - limit))}
          className="btn-secondary btn-sm disabled:opacity-50"
        >
          上一页
        </button>
        <span className="text-theme-muted">{offset + 1} - {Math.min(offset + limit, total)} / {total}</span>
        <button
          disabled={offset + limit >= total}
          onClick={() => setOffset((p) => p + limit)}
          className="btn-secondary btn-sm disabled:opacity-50"
        >
          下一页
        </button>
      </div>
    </div>
  );
}

function PanelLoading() {
  return (
    <div className="flex items-center justify-center py-12 text-theme-muted">
      <Loader2 className="w-5 h-5 animate-spin mr-2 text-accent" />
      加载中...
    </div>
  );
}
