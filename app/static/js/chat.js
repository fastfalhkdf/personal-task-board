/**
 * 对话抽屉与工具轨迹（设计方案 §7.1 js/chat.js，付佳宝）。
 *
 * - init(ctx) 挂载契约同 js/app.js（D1 自造的参数契约已废弃）；
 * - 携带最近 10 轮 history（契约 §5.1，服务端无状态，不建会话表）；
 * - 待确认卡片交 pending.js 渲染：动态 import，pending.js 出错不拖垮对话（互不等待）。
 */
import api from './api.js';

/** 最近 10 轮 = user/assistant 各 10 条（契约 §5.1 的裁剪规则）。 */
const HISTORY_LIMIT = 20;

let ctx = null;
let bound = false;
const history = [];

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[char]);
}

function appendMessage(role, text) {
  const box = document.querySelector('#messages');
  if (!box) return;
  const node = document.createElement('div');
  node.className = `msg ${role}`;
  node.textContent = text;
  box.appendChild(node);
  box.scrollTop = box.scrollHeight;
}

function renderTrace(result) {
  const trace = document.querySelector('#trace');
  if (!trace) return;
  const steps = (result.steps || [])
    .map(
      (step) =>
        `<div>${escapeHtml(step.kind)} ${escapeHtml(step.tool || '')}<br>${escapeHtml(
          step.content,
        )}</div>`,
    )
    .join('');
  trace.innerHTML = `<summary>调用轨迹 ${Number(result.tool_calls) || 0} 次</summary>${steps}`;
}

function pushHistory(role, content) {
  history.push({ role, content });
  if (history.length > HISTORY_LIMIT) history.splice(0, history.length - HISTORY_LIMIT);
}

async function send() {
  const input = document.querySelector('#question');
  const question = (input?.value || '').trim();
  if (!question) return;
  appendMessage('user', question);
  pushHistory('user', question);
  if (input) input.value = '';
  try {
    const result = await api.agent.run(question, history);
    appendMessage('assistant', result.answer);
    pushHistory('assistant', result.answer);
    renderTrace(result);
    try {
      const pending = await import('./pending.js');
      // 优先按服务端列表回拉（含此前未处理的）；拉不到就用本次响应兜底，保证卡片不丢
      await pending
        .refreshFromServer()
        .catch(() => pending.render && pending.render(result.pending_writes || []));
    } catch (error) {
      console.warn('[chat] pending.js 未就绪，待确认卡片暂不可用', error);
    }
  } catch (error) {
    appendMessage('assistant', `失败：${(error && error.message) || '请求出错'}`);
  }
}

export function init(context) {
  ctx = context;
  if (bound) return;
  bound = true;
  document.querySelector('#send')?.addEventListener('click', send);
}
