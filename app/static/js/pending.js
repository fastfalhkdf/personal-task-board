/**
 * 待确认面板：字段级 diff 卡片 + 确认/取消（设计方案 §7.1 js/pending.js，付佳宝）。
 *
 * 契约（docs/api-contract.md §5，郑伟健）：
 *   - §5.1 run 响应 pending_writes[]：{id, tool, args, before, after, expires_at}
 *   - §5.2 GET /api/agent/pending：刷新页面后待确认找回（验收 11）
 *   - §5.3 confirm：确认执行、重复确认幂等；§5.4 cancel：拒绝，状态 cancelled
 * 渲染规则：
 *   - update 类（before 非空）逐字段渲染"改前 → 改后"（验收 12，D1 留的注释就是等它）
 *   - create 类（before 为空）沿用 D1 约定：展示 args 原文
 *   - 确认成功后让看板/统计重新拉取（syncBoard，见注释）
 */
import api from './api.js';

let ctx = null;
let wired = false;

const TOOL_LABEL = {
  create_task: '创建任务',
  update_task: '更新任务',
  delete_task: '删除任务',
};

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[char]);
}

function toast(message) {
  if (ctx && typeof ctx.toast === 'function') {
    ctx.toast(message);
    return;
  }
  const el = document.querySelector('#toast');
  if (!el) return;
  el.textContent = message;
  el.classList.remove('hidden');
  setTimeout(() => el.classList.add('hidden'), 2500);
}

function formatValue(value) {
  if (value === undefined) return '—';
  if (value === null) return '空';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

/** 过期时间是服务端 naive UTC（契约 §0），补 Z 再按本地时区显示。 */
function expiresLabel(iso) {
  if (!iso) return '';
  const text = /Z|[+-]\d{2}:\d{2}$/.test(iso) ? iso : `${iso}Z`;
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) return '';
  return `${date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })} 过期`;
}

function diffHtml(before, after) {
  const keys = [...new Set([...Object.keys(before || {}), ...Object.keys(after || {})])];
  return keys
    .map((key) => {
      const from = formatValue((before || {})[key]);
      const to = formatValue((after || {})[key]);
      const changed = from !== to;
      return (
        `<div class="diff-field"${changed ? ' data-changed="1"' : ''}>` +
        `<code>${escapeHtml(key)}</code>：${escapeHtml(from)} → <strong>${escapeHtml(to)}</strong>` +
        '</div>'
      );
    })
    .join('');
}

function cardHtml(item) {
  const before = item.before || {};
  const hasBefore = Object.keys(before).length > 0;
  const label = TOOL_LABEL[item.tool] || item.tool;
  const body = hasBefore
    ? diffHtml(before, item.after || {})
    : `<pre>${escapeHtml(JSON.stringify(item.args || {}, null, 2))}</pre>`;
  return (
    `<div class="pending-card" data-id="${escapeHtml(item.id)}">` +
    `<div class="pending-head"><strong>${escapeHtml(label)}</strong>` +
    `<span class="muted"> ${escapeHtml(expiresLabel(item.expires_at))}</span></div>` +
    body +
    '<div class="pending-actions">' +
    `<button class="btn" type="button" data-confirm="${escapeHtml(item.id)}">确认写入</button>` +
    `<button class="btn btn-ghost" type="button" data-cancel="${escapeHtml(item.id)}">取消</button>` +
    '</div></div>'
  );
}

/** 直接用给定数据画卡片；refreshFromServer 失败时由 chat.js 用 run 响应兜底。 */
export function render(rows) {
  const box = document.querySelector('#pending');
  if (!box) return;
  box.innerHTML = (rows || []).map(cardHtml).join('');
}

/** 从服务端回拉我的待确认列表（验收 11：刷新页面后仍可找回）。 */
export async function refreshFromServer() {
  const payload = await api.agent.pending();
  render(payload && payload.items ? payload.items : []);
  return payload;
}

/**
 * 让看板/统计重新拉取：board.js 只对外提供 onTasksChanged 单向订阅，没有刷新出口，
 * 这里重新触发项目切换器的 change 事件，让它走自己的切换流程（重载任务与成员）。
 * 只依赖公开 DOM 交互，不改他人文件（规范 §5.2 红线②）。
 */
function syncBoard() {
  const switcher = document.querySelector('#project-switcher');
  if (switcher) switcher.dispatchEvent(new Event('change'));
}

async function handleConfirm(button) {
  const id = button.dataset.confirm;
  button.disabled = true;
  try {
    await api.agent.confirm(id);
    toast('已写入');
    await refreshFromServer().catch(() => {});
    syncBoard();
  } catch (error) {
    toast(error.message);
    // 409（已过期/已取消）等状态变化时按服务端真实状态重画
    await refreshFromServer().catch(() => {});
  }
}

async function handleCancel(button) {
  const id = button.dataset.cancel;
  button.disabled = true;
  try {
    await api.agent.cancel(id);
    toast('已取消');
    await refreshFromServer().catch(() => {});
    syncBoard();
  } catch (error) {
    toast(error.message);
    await refreshFromServer().catch(() => {});
  }
}

function handleClick(event) {
  const confirmButton = event.target.closest('[data-confirm]');
  if (confirmButton) {
    handleConfirm(confirmButton);
    return;
  }
  const cancelButton = event.target.closest('[data-cancel]');
  if (cancelButton) handleCancel(cancelButton);
}

export function init(context) {
  ctx = context;
  if (!wired) {
    wired = true;
    document.querySelector('#pending')?.addEventListener('click', handleClick);
  }
  // 验收 11：进页面先把服务端挂着的待确认捞回来；失败静默（未登录/无记录都属正常）
  refreshFromServer().catch(() => {});
}
