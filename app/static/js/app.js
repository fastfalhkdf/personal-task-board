/**
 * 挂载入口（设计方案 §7.1 的 js/app.js，卓江城维护）。
 *
 * 只做三件事：
 *   1. 会话检查：GET /api/auth/me 决定显示登录卡片还是主视图；
 *   2. 壳交互：.hidden 视图切换、右侧抽屉开合、<dialog> 的 data-close；
 *   3. 动态挂载业务模块：某个 js/*.js 还没入库时只告警，不拖垮别的模块。
 *
 * 模块契约：每个 js/*.js 可以导出 `async function init(ctx)`，ctx 见下方 makeContext()。
 *   - board.js / stats.js / task-card.js（卓江城）
 *   - chat.js / pending.js / members.js / auth.js（付佳宝）
 * ./auth.js 到位时这里完全不碰登录表单；它没到位时才用内置的降级登录兜底。
 */
import api from './api.js';

/** 挂载顺序：看板与统计先出内容，对话/成员随后。缺文件自动跳过。 */
const MODULES = ['./board.js', './stats.js', './chat.js', './pending.js', './members.js'];

const TOAST_MS = 2600;

const $ = (selector) => document.querySelector(selector);

const state = {
  user: null,
  mounted: new Set(),
  toastTimer: 0,
};

/** 全局提示：写 #toast 文本，2.6 秒后自动收起（index.html 里的 .toast 样式）。 */
function toast(message) {
  const el = $('#toast');
  if (!el) return;
  el.textContent = String(message ?? '');
  el.classList.remove('hidden');
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => el.classList.add('hidden'), TOAST_MS);
}

function showApp(user) {
  const authView = $('#auth');
  const appView = $('#app');
  // 只在类名真的变化时才写 DOM：classList.remove() 即使 token 不存在也会写 class 属性，
  // 那会再次触发下面的 MutationObserver，和 enterApp 组成死循环（实测能把主线程卡死）。
  if (authView && !authView.classList.contains('hidden')) authView.classList.add('hidden');
  if (appView && appView.classList.contains('hidden')) appView.classList.remove('hidden');
  const nameEl = $('#user-name');
  if (nameEl) nameEl.textContent = (user && (user.name || user.email)) || '';
}

function showLogin() {
  closeDrawer();
  const authView = $('#auth');
  const appView = $('#app');
  if (authView && authView.classList.contains('hidden')) authView.classList.remove('hidden');
  if (appView && !appView.classList.contains('hidden')) appView.classList.add('hidden');
}

/* ---------- 右侧抽屉 ---------- */

function openDrawer() {
  document.body.classList.add('drawer-open');
  const drawer = $('#drawer');
  const backdrop = $('#drawer-backdrop');
  const toggle = $('#drawer-toggle');
  if (drawer) drawer.setAttribute('aria-hidden', 'false');
  if (backdrop) backdrop.classList.remove('hidden');
  if (toggle) toggle.setAttribute('aria-expanded', 'true');
}

function closeDrawer() {
  document.body.classList.remove('drawer-open');
  const drawer = $('#drawer');
  const backdrop = $('#drawer-backdrop');
  const toggle = $('#drawer-toggle');
  if (drawer) drawer.setAttribute('aria-hidden', 'true');
  if (backdrop) backdrop.classList.add('hidden');
  if (toggle) toggle.setAttribute('aria-expanded', 'false');
}

function toggleDrawer() {
  if (document.body.classList.contains('drawer-open')) closeDrawer();
  else openDrawer();
}

/* ---------- 壳交互 ---------- */

function wireShell() {
  $('#drawer-toggle')?.addEventListener('click', toggleDrawer);
  $('#drawer-close')?.addEventListener('click', closeDrawer);
  $('#drawer-backdrop')?.addEventListener('click', closeDrawer);

  // 弹窗右上角/取消按钮统一走 data-close，交给原生 dialog.close()
  document.addEventListener('click', (event) => {
    const closer = event.target.closest('[data-close]');
    if (!closer) return;
    const dialog = closer.closest('dialog');
    if (dialog) dialog.close();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    if (document.body.classList.contains('drawer-open')) {
      closeDrawer();
      return;
    }
    document.querySelectorAll('dialog[open]').forEach((dialog) => dialog.close());
  });
}

/* ---------- 登录（auth.js 未就绪时的兜底） ---------- */

function showAuthError(message) {
  const errorEl = $('#auth-error');
  if (!errorEl) {
    toast(message);
    return;
  }
  errorEl.textContent = message;
  errorEl.classList.remove('hidden');
}

function clearAuthError() {
  const errorEl = $('#auth-error');
  if (!errorEl) return;
  errorEl.textContent = '';
  errorEl.classList.add('hidden');
}

async function submitLogin() {
  const email = ($('#email')?.value || '').trim();
  const password = $('#password')?.value || '';
  clearAuthError();
  if (!email || !password) {
    showAuthError('请填写邮箱和密码');
    return;
  }
  const button = $('#login');
  if (button) button.disabled = true;
  try {
    const payload = await api.auth.login(email, password);
    await enterApp(payload && payload.user);
  } catch (error) {
    showAuthError((error && error.message) || '登录失败');
  } finally {
    if (button) button.disabled = false;
  }
}

async function submitLogout() {
  try {
    await api.auth.logout();
  } catch (error) {
    console.warn('[app] 退出接口失败，仍按未登录处理', error);
  }
  location.reload();
}

function wireLoginFallback() {
  const button = $('#login');
  if (!button || button.dataset.fallbackBound === '1') return;
  button.dataset.fallbackBound = '1';
  button.addEventListener('click', submitLogin);
  $('#logout')?.addEventListener('click', submitLogout);
}

/* ---------- 模块挂载 ---------- */

async function loadModule(path) {
  try {
    return await import(path);
  } catch (error) {
    console.warn(`[app] 模块尚未就绪，跳过：${path}`, (error && error.message) || error);
    return null;
  }
}

function makeContext() {
  return {
    api,
    get user() {
      return state.user;
    },
    getUser: () => state.user,
    toast,
    onLoggedIn: (user) => enterApp(user),
    onLogout: () => submitLogout(),
    closeDrawer,
  };
}

const ctx = makeContext();

async function mountModule(path) {
  if (state.mounted.has(path)) return;
  const module = await loadModule(path);
  if (!module || typeof module.init !== 'function') return;
  try {
    await module.init(ctx);
    state.mounted.add(path);
  } catch (error) {
    console.error(`[app] 模块初始化失败：${path}`, error);
  }
}

/** 并发保护：重复调用只会挂一轮，避免多个入口同时初始化同一批模块。 */
let mounting = null;

function mountModules() {
  if (mounting) return mounting;
  mounting = Promise.all(MODULES.map((path) => mountModule(path))).finally(() => {
    mounting = null;
  });
  return mounting;
}

async function enterApp(user) {
  state.user = user || null;
  showApp(state.user);
  await mountModules();
}

/**
 * #app 从隐藏变为可见时补挂模块（auth.js 自己切视图也算），
 * 避免"登录成功但看板空白"。只在"假→真"这一次跳变时触发，
 * 不要写成"只要可见就套 enterApp"——那会和 showApp 的类名写入互相触发。
 */
function watchAppVisibility() {
  const appView = $('#app');
  if (!appView || typeof MutationObserver === 'undefined') return;
  let wasVisible = !appView.classList.contains('hidden');
  const observer = new MutationObserver(async () => {
    const visible = !appView.classList.contains('hidden');
    const justBecameVisible = visible && !wasVisible;
    wasVisible = visible;
    if (!justBecameVisible || state.mounted.size > 0) return;
    const user = state.user || (await api.auth.me().catch(() => null));
    if (user) await enterApp(user);
  });
  observer.observe(appView, { attributes: true, attributeFilter: ['class'] });
}

/* ---------- 启动 ---------- */

async function boot() {
  wireShell();
  watchAppVisibility();

  const authModule = await loadModule('./auth.js');
  if (authModule && typeof authModule.init === 'function') {
    try {
      await authModule.init(ctx);
    } catch (error) {
      console.error('[app] auth.js 初始化失败，改用内置登录兜底', error);
    }
  }

  const user = await api.auth.me().catch(() => null);
  if (user) {
    await enterApp(user);
    return;
  }

  showLogin();
  if (!(authModule && typeof authModule.init === 'function')) wireLoginFallback();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    boot().catch((error) => console.error('[app] 启动失败', error));
  });
} else {
  boot().catch((error) => console.error('[app] 启动失败', error));
}
