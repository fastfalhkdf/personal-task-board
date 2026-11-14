/**
 * 登录与退出（设计方案 §7.1 js/auth.js，付佳宝名下）。
 *
 * 挂载契约以 js/app.js 为准：init(ctx)。本模块只负责表单提交、回车提交与错误提示；
 * 视图切换、会话恢复、业务模块挂载全部由 app.js 负责。
 * （D1 自造的 init({onSessionChange}) 参数契约已废弃——合并 app.js 后那套接不上。）
 */
import api from './api.js';

let bound = false;

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

async function submitLogin(ctx) {
  const email = (document.querySelector('#email')?.value || '').trim();
  const password = document.querySelector('#password')?.value || '';
  clearError();
  if (!email || !password) {
    showError(ctx, '请填写邮箱和密码');
    return;
  }
  const button = document.querySelector('#login');
  if (button) button.disabled = true;
  try {
    const payload = await api.auth.login(email, password);
    if (ctx && typeof ctx.onLoggedIn === 'function') {
      await ctx.onLoggedIn(payload && payload.user);
    }
  } catch (error) {
    showError(ctx, (error && error.message) || '登录失败');
  } finally {
    if (button) button.disabled = false;
  }
}

export function init(ctx) {
  if (bound) return;
  bound = true;

  document.querySelector('#login')?.addEventListener('click', () => submitLogin(ctx));

  // 登录卡片不是 <form>，回车不会提交——补上（#login 本身是 type=button，无默认提交）
  ['#email', '#password'].forEach((selector) => {
    document.querySelector(selector)?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        submitLogin(ctx);
      }
    });
  });

  document.querySelector('#logout')?.addEventListener('click', () => {
    if (ctx && typeof ctx.onLogout === 'function') ctx.onLogout();
  });
}
