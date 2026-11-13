// 登录态与会话守卫：登录、退出、启动时恢复会话（设计方案 §7.1，付佳宝名下）
// index.html 不归本人维护：本模块等待卓江城的 js/app.js 动态 import 后调用 init()，
// 在那之前页面仍由原内联脚本驱动，行为不变。
import { request } from '../request.js';

function toast(message) {
  const el = document.querySelector('#toast');
  el.textContent = message;
  el.classList.remove('hidden');
  setTimeout(() => el.classList.add('hidden'), 2500);
}

// onSessionChange：登录成功或已登录时刷新页面状态（统计条归 js/stats.js，由挂载方注入）
export function init({ onSessionChange } = {}) {
  const $ = s => document.querySelector(s);

  async function notify() {
    if (onSessionChange) await onSessionChange();
  }

  async function login() {
    try {
      await request('/api/auth/login', {
        method: 'POST',
        body: { email: $('#email').value, password: $('#password').value },
      });
      $('#auth').classList.add('hidden');
      $('#app').classList.remove('hidden');
      await notify();
    } catch (error) {
      toast(error.message);
    }
  }

  $('#login').onclick = login;
  $('#logout').onclick = async () => {
    await request('/api/auth/logout', { method: 'POST' });
    location.reload();
  };

  // 已有会话则直接进入应用页，失败保持在登录页
  request('/api/auth/me')
    .then(async () => {
      $('#auth').classList.add('hidden');
      $('#app').classList.remove('hidden');
      await notify();
    })
    .catch(() => {});
}
