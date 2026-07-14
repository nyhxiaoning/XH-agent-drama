import { create } from 'zustand';
import { api } from '@/utils/api';

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

interface AuthState {
  token: string | null;
  user: User | null;
  isLoading: boolean;
  error: string | null;

  setToken: (token: string | null) => void;
  setUser: (user: User | null) => void;
  login: (account: string, password: string, type?: 'email' | 'phone') => Promise<void>;
  loginSms: (phone: string, code: string, name?: string, password?: string) => Promise<void>;
  register: (email: string, password: string, name?: string) => Promise<void>;
  logout: () => void;
  fetchMe: () => Promise<void>;
  isAuthenticated: () => boolean;
}

const TOKEN_KEY = 'xiaoyunque_token';

function getStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: getStoredToken(),
  user: null,
  isLoading: false,
  error: null,

  setToken: (token) => {
    if (token) {
      localStorage.setItem(TOKEN_KEY, token);
    } else {
      localStorage.removeItem(TOKEN_KEY);
    }
    set({ token });
  },

  setUser: (user) => set({ user }),

  login: async (account, password, type = 'email') => {
    set({ isLoading: true, error: null });
    try {
      const res = await api.login(type === 'email' ? { email: account, password } : { phone: account, password });
      get().setToken(res.access_token);
      await get().fetchMe();
    } catch (err: any) {
      set({ error: err.message || '登录失败' });
      throw err;
    } finally {
      set({ isLoading: false });
    }
  },

  loginSms: async (phone, code, name, password) => {
    set({ isLoading: true, error: null });
    try {
      const res = await api.loginSms(phone, code, name, password);
      get().setToken(res.access_token);
      await get().fetchMe();
    } catch (err: any) {
      set({ error: err.message || '登录失败' });
      throw err;
    } finally {
      set({ isLoading: false });
    }
  },

  register: async (email, password, name) => {
    set({ isLoading: true, error: null });
    try {
      await api.register(email, password, name);
      await get().login(email, password);
    } catch (err: any) {
      set({ error: err.message || '注册失败' });
      throw err;
    } finally {
      set({ isLoading: false });
    }
  },

  logout: () => {
    get().setToken(null);
    set({ user: null, error: null });
  },

  fetchMe: async () => {
    const token = get().token;
    if (!token) return;
    try {
      const user = await api.me();
      set({ user });
    } catch {
      get().setToken(null);
      set({ user: null });
    }
  },

  isAuthenticated: () => !!get().token,
}));
