import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/store/auth';
import { api } from '@/utils/api';
import type { UserStats, CreditLedgerList } from '@/utils/api';
import {
  LogOut, Coins, Shield, Mail, Receipt, BarChart3, Lock,
  Wallet, ArrowRight, LayoutDashboard, Feather, Loader2
} from 'lucide-react';

export default function ProfilePage() {
  const navigate = useNavigate();
  const { user, logout, fetchMe, isAuthenticated } = useAuthStore();
  const [ledger, setLedger] = useState<CreditLedgerList | null>(null);
  const [stats, setStats] = useState<UserStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [offset, setOffset] = useState(0);
  const limit = 20;
  const [ledgerOpen, setLedgerOpen] = useState(false);
  const ledgerRef = useRef<HTMLDivElement>(null);

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [passwordSuccess, setPasswordSuccess] = useState('');

  useEffect(() => {
    if (!isAuthenticated()) {
      navigate('/login');
      return;
    }
    fetchMe();
    setLoading(true);
    Promise.all([
      api.getMyLedger(limit, offset).then(setLedger).catch(() => setLedger({ total: 0, items: [], balance: 0 })),
      api.getMyStats().then(setStats).catch(() => setStats(null)),
    ]).finally(() => setLoading(false));
  }, [isAuthenticated, navigate, fetchMe, offset]);

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const toggleLedger = () => {
    setLedgerOpen((v) => !v);
    setTimeout(() => {
      ledgerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 50);
  };

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setPasswordError('');
    setPasswordSuccess('');
    try {
      await api.changePassword(currentPassword || null, newPassword);
      setPasswordSuccess('密码修改成功');
      setCurrentPassword('');
      setNewPassword('');
    } catch (err: any) {
      setPasswordError(err.message || '修改失败');
    }
  };

  if (!user) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-canvas-bg text-theme-muted animate-fade-in">
        <Loader2 className="w-6 h-6 animate-spin text-accent mr-2" />
        加载中...
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-canvas-bg text-theme-main p-6 pt-24 pb-24 overflow-y-auto animate-fade-in">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-teal-600 to-emerald-700 flex items-center justify-center shadow-glow">
              <Feather size={18} className="text-theme-invert" />
            </div>
            <h1 className="text-2xl font-bold text-theme-main">用户中心</h1>
          </div>
          <button
            onClick={() => navigate('/home')}
            className="btn-ghost"
          >
            返回画布
          </button>
        </div>

        {/* 用户信息 */}
        <div className="card p-6 mb-6">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-4">
              {user.avatar_url ? (
                <img src={user.avatar_url} alt="avatar" className="w-16 h-16 rounded-full object-cover border-2 border-panel-border" />
              ) : (
                <div className="w-16 h-16 rounded-full bg-gradient-to-br from-teal-600 to-emerald-700 flex items-center justify-center text-theme-invert text-2xl font-bold shadow-glow">
                  {(user.name || user.email || 'U')[0].toUpperCase()}
                </div>
              )}
              <div>
                <div className="text-xl font-semibold text-theme-main">{user.name || '未命名用户'}</div>
                <div className="text-sm text-theme-muted flex items-center gap-1 mt-1">
                  <Mail className="w-3.5 h-3.5" />
                  {user.email || '未绑定邮箱'}
                </div>
                <div className="text-xs text-theme-sub mt-1">
                  注册于 {new Date(user.created_at).toLocaleDateString()}
                </div>
              </div>
            </div>
            <button
              onClick={handleLogout}
              className="btn-danger shrink-0"
            >
              <LogOut className="w-4 h-4" />
              退出登录
            </button>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="rounded-xl glass p-4">
              <div className="flex items-center gap-2 text-theme-muted text-sm mb-1">
                <Coins className="w-4 h-4" />
                剩余积分
              </div>
              <div className="text-2xl font-bold text-accent">{user.credits}</div>
            </div>
            <div className="rounded-xl glass p-4">
              <div className="flex items-center gap-2 text-theme-muted text-sm mb-1">
                <Shield className="w-4 h-4" />
                身份
              </div>
              <div className="text-lg font-medium text-theme-main">{user.is_admin ? '管理员' : '普通用户'}</div>
            </div>
            <div className="rounded-xl glass p-4">
              <div className="flex items-center gap-2 text-theme-muted text-sm mb-1">
                <BarChart3 className="w-4 h-4" />
                画布数
              </div>
              <div className="text-2xl font-bold text-theme-main">{stats?.canvas_count ?? '-'}</div>
            </div>
            <div className="rounded-xl glass p-4">
              <div className="flex items-center gap-2 text-theme-muted text-sm mb-1">
                <Receipt className="w-4 h-4" />
                本月消耗
              </div>
              <div className="text-2xl font-bold text-theme-main">{stats?.credits_used_this_month ?? '-'}</div>
            </div>
          </div>
        </div>

        {/* 用量统计 */}
        <div className="card p-6 mb-6">
          <div className="flex items-center gap-2 text-theme-muted text-sm mb-4">
            <BarChart3 className="w-4 h-4" />
            生成用量
          </div>
          {loading ? (
            <div className="flex items-center gap-2 text-sm text-theme-muted">
              <Loader2 className="w-4 h-4 animate-spin" />
              加载中...
            </div>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <StatBox label="图片" value={stats?.image_count ?? 0} />
              <StatBox label="视频" value={stats?.video_count ?? 0} />
              <StatBox label="剧本" value={stats?.script_count ?? 0} />
              <StatBox label="音频" value={stats?.audio_count ?? 0} />
            </div>
          )}
        </div>

        {/* 快捷入口 */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
          <button
            onClick={() => navigate('/recharge')}
            className="card p-5 flex items-center justify-between hover:-translate-y-0.5 hover:shadow-soft-lg hover:border-accent/40 transition-all text-left"
          >
            <div>
              <div className="font-semibold flex items-center gap-2 text-theme-main">
                <Wallet className="w-4 h-4 text-accent" />
                积分充值
              </div>
              <div className="text-xs text-theme-muted mt-1">兑换码 / 支付宝 / 微信</div>
            </div>
            <ArrowRight className="w-4 h-4 text-theme-muted" />
          </button>

          <button
            onClick={toggleLedger}
            className="card p-5 flex items-center justify-between hover:-translate-y-0.5 hover:shadow-soft-lg hover:border-accent/40 transition-all text-left"
          >
            <div>
              <div className="font-semibold flex items-center gap-2 text-theme-main">
                <Receipt className="w-4 h-4 text-accent" />
                积分流水
              </div>
              <div className="text-xs text-theme-muted mt-1">点击查看积分明细记录</div>
            </div>
            <ArrowRight className="w-4 h-4 text-theme-muted" />
          </button>

          {user.is_admin && (
            <button
              onClick={() => navigate('/admin')}
              className="card p-5 flex items-center justify-between hover:-translate-y-0.5 hover:shadow-soft-lg hover:border-accent/40 transition-all text-left"
            >
              <div>
                <div className="font-semibold flex items-center gap-2 text-theme-main">
                  <LayoutDashboard className="w-4 h-4 text-accent" />
                  管理员后台
                </div>
                <div className="text-xs text-theme-muted mt-1">用户 / 积分 / 模型 / 公告</div>
              </div>
              <ArrowRight className="w-4 h-4 text-theme-muted" />
            </button>
          )}
        </div>

        {/* 修改密码 */}
        <div className="card p-6 mb-6">
          <div className="flex items-center gap-2 text-theme-muted text-sm mb-4">
            <Lock className="w-4 h-4" />
            修改密码
          </div>
          <form onSubmit={handleChangePassword} className="space-y-3">
            <input
              type="password"
              placeholder="当前密码（未设置过可留空）"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              className="input-field"
            />
            <input
              type="password"
              placeholder="新密码（至少6位）"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              minLength={6}
              className="input-field"
            />
            {passwordError && <div className="error-alert">{passwordError}</div>}
            {passwordSuccess && <div className="success-alert">{passwordSuccess}</div>}
            <button
              type="submit"
              className="btn-primary"
            >
              确认修改
            </button>
          </form>
        </div>

        {/* 积分流水 */}
        {ledgerOpen && (
          <div ref={ledgerRef} className="card p-6 mb-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2 text-theme-muted text-sm">
                <Receipt className="w-4 h-4" />
                积分流水
              </div>
              <button
                onClick={() => setLedgerOpen(false)}
                className="btn-ghost text-xs"
              >
                收起
              </button>
            </div>
            {loading ? (
              <div className="flex items-center gap-2 text-sm text-theme-muted">
                <Loader2 className="w-4 h-4 animate-spin" />
                加载中...
              </div>
            ) : !ledger || ledger.items.length === 0 ? (
              <div className="text-sm text-theme-muted">暂无积分流水</div>
            ) : (
              <div className="space-y-2 max-h-80 overflow-auto pr-1">
                {ledger.items.map((item) => (
                  <div
                    key={item.id}
                    className="flex items-center justify-between rounded-xl glass p-3 text-sm"
                  >
                    <div className="min-w-0">
                      <div className="font-medium truncate text-theme-main">
                        {item.description || item.reason}
                      </div>
                      <div className="text-xs text-theme-sub">
                        {new Date(item.created_at).toLocaleString()}
                      </div>
                    </div>
                    <div className="flex flex-col items-end ml-3 shrink-0">
                      <span className={item.amount > 0 ? 'text-success font-semibold' : 'text-warning font-semibold'}>
                        {item.amount > 0 ? '+' : ''}{item.amount}
                      </span>
                      <span className="text-xs text-theme-muted">余额 {item.balance_after}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {ledger && ledger.total > limit && (
              <div className="flex items-center justify-between text-sm mt-4">
                <button
                  disabled={offset === 0}
                  onClick={() => setOffset((p) => Math.max(0, p - limit))}
                  className="btn-secondary btn-sm disabled:opacity-50"
                >
                  上一页
                </button>
                <span className="text-theme-muted">{offset + 1} - {Math.min(offset + limit, ledger.total)} / {ledger.total}</span>
                <button
                  disabled={offset + limit >= ledger.total}
                  onClick={() => setOffset((p) => p + limit)}
                  className="btn-secondary btn-sm disabled:opacity-50"
                >
                  下一页
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function StatBox({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl glass p-3 text-center">
      <div className="text-lg font-bold text-theme-main">{value}</div>
      <div className="text-xs text-theme-muted">{label}</div>
    </div>
  );
}
