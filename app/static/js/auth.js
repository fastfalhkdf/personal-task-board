/**
 * 登录与退出（设计方案 §7.1 js/auth.js，付佳宝名下）。
 *
 * 挂载契约以 js/app.js 为准：init(ctx)。本模块只负责表单提交、回车提交与错误提示；
 * 视图切换、会话恢复、业务模块挂载全部由 app.js 负责。
 * （D1 自造的 init({onSessionChange}) 参数契约已废弃——合并 app.js 后那套接不上。）
 */
import api from './api.js';

let bound = false;
let mode = 'login'; // 'login' | 'register'

function setMode(next) {
  mode = next;
  document.querySelector('#name-field')?.classList.toggle('hidden', mode === 'login');
  const button = document.querySelector('#login');
  if (button) button.textContent = mode === 'login' ? '登录' : '注册';
  const toggle = document.querySelector('#auth-toggle');
  if (toggle) toggle.textContent = mode === 'login' ? '还没有账号？注册' : '已有账号？登录';
  clearError();
}

function showError(ctx, message) {
  const el = document.querySelector('#auth-error');
  if (el) {
    el.textContent = message;
    el.classList.remove('hidden');
    return;
  }
  if (ctx && typeof ctx.toast === 'function') ctx.toast(message);
}

function clearError() {
  const el = document.querySelector('#auth-error');
  if (!el) return;
  el.textContent = '';
  el.classList.add('hidden');
}

async function submitAuth(ctx) {
  const email = (document.querySelector('#email')?.value || '').trim();
  const password = document.querySelector('#password')?.value || '';
  const name = (document.querySelector('#name')?.value || '').trim();
  clearError();
  if (mode === 'register') {
    if (!name || !email || !password) {
      showError(ctx, '请填写昵称、邮箱和密码');
      return;
    }
    if (password.length < 8) {
      showError(ctx, '密码至少 8 位');
      return;
    }
  } else if (!email || !password) {
    showError(ctx, '请填写邮箱和密码');
    return;
  }
  const button = document.querySelector('#login');
  if (button) button.disabled = true;
  try {
    let payload;
    if (mode === 'register') {
      // 后端 /api/auth/register（201，重复邮箱 409），注册成功后自动登录进入
      await api.auth.register({ email, name, password });
      payload = await api.auth.login(email, password);
      setMode('login');
    } else {
      payload = await api.auth.login(email, password);
    }
    if (ctx && typeof ctx.onLoggedIn === 'function') {
      await ctx.onLoggedIn(payload && payload.user);
    }
  } catch (error) {
    showError(ctx, (error && error.message) || (mode === 'register' ? '注册失败' : '登录失败'));
  } finally {
    if (button) button.disabled = false;
  }
}

export function init(ctx) {
  if (bound) return;
  bound = true;

  document.querySelector('#login')?.addEventListener('click', () => submitAuth(ctx));

  document.querySelector('#auth-toggle')?.addEventListener('click', () => {
    setMode(mode === 'login' ? 'register' : 'login');
  });

  // 登录卡片不是 <form>，回车不会提交——补上（#login 本身是 type=button，无默认提交）
  ['#email', '#password', '#name'].forEach((selector) => {
    document.querySelector(selector)?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        submitAuth(ctx);
      }
    });
  });

  document.querySelector('#logout')?.addEventListener('click', () => {
    if (ctx && typeof ctx.onLogout === 'function') ctx.onLogout();
  });
}
