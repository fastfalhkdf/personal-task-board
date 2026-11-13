// 对话抽屉与工具轨迹（设计方案 §7.1，付佳宝名下）
// 只拆分不改行为：提问 → /api/agent/run → 回答 + 轨迹折叠 + 交给 pending 渲染待确认卡片。
// renderPending 由挂载方（js/app.js）注入，本模块不 import pending.js，避免互相等待。
import { request } from '../request.js';

function toast(message) {
  const el = document.querySelector('#toast');
  el.textContent = message;
  el.classList.remove('hidden');
  setTimeout(() => el.classList.add('hidden'), 2500);
}

function appendMessage(role, text) {
  const node = document.createElement('div');
  node.className = `msg ${role}`;
  node.textContent = text;
  const box = document.querySelector('#messages');
  box.appendChild(node);
  box.scrollTop = box.scrollHeight;
}

function renderTrace(result) {
  document.querySelector('#trace').innerHTML =
    `<summary>调用轨迹 ${result.tool_calls} 次</summary>` +
    (result.steps || [])
      .map(step => `<div>${step.kind} ${step.tool || ''}<br>${step.content}</div>`)
      .join('');
}

export function init({ renderPending } = {}) {
  const $ = s => document.querySelector(s);

  async function send() {
    const question = $('#question').value.trim();
    if (!question) return;
    appendMessage('user', question);
    $('#question').value = '';
    try {
      const result = await request('/api/agent/run', {
        method: 'POST',
        body: { question, max_steps: 6 },
        timeout: 60000,
      });
      appendMessage('assistant', result.answer);
      renderTrace(result);
      if (renderPending) renderPending(result.pending_writes);
    } catch (error) {
      appendMessage('assistant', `失败：${error.message}`);
    }
  }

  $('#send').onclick = send;
}
