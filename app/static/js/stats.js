/**
 * 统计面板（设计方案 §7.1 的 js/stats.js，卓江城维护）。
 *
 * 今日到期数 / 逾期数 / 完成率 + 按状态、项目、成员的 CSS 条形图 + 今日待办列表。
 * 数据订阅 board.js 的任务列表（onTasksChanged），保证面板数字与看板完全一致；
 * 服务端 /api/tasks/today 与 /api/tasks/stats 落地后可以改成服务端聚合——
 * 现在客户端算，7 条 mock 的量级完全够用，也不会出现"看板 4 条、面板 3 条"的对不上。
 *
 * 点今日列表里的条目直接打开编辑弹窗（复用 task-card.js 的 openEditor）。
 */
import { getMembers, getProjects, getTasks, onTasksChanged } from './board.js';
import { openEditor } from './task-card.js';

const STATUS_LABEL = { todo: '待办', in_progress: '进行中', blocked: '阻塞', done: '已完成' };
const STATUS_ORDER = ['todo', 'in_progress', 'blocked', 'done'];
const UNSET = '未指派';

const $ = (selector) => document.querySelector(selector);

const state = {
  ctx: null,
};

/* ---------- 小工具 ---------- */

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[char]);
}

function todayIso() {
  const date = new Date();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${date.getFullYear()}-${month}-${day}`;
}

/* ---------- 计算 ---------- */

function compute(tasks) {
  const today = todayIso();
  const open = tasks.filter((task) => task.status !== 'done');
  const todayDue = open.filter((task) => task.due_date === today);
  const overdue = open.filter((task) => task.due_date && task.due_date < today);
  const done = tasks.filter((task) => task.status === 'done');
  const rate = tasks.length === 0 ? 0 : Math.round((done.length / tasks.length) * 100);
  return { total: tasks.length, open, todayDue, overdue, done, rate };
}

function countBy(tasks, keyFn) {
  const map = new Map();
  tasks.forEach((task) => {
    const key = keyFn(task);
    map.set(key, (map.get(key) || 0) + 1);
  });
  return [...map.entries()].sort((a, b) => b[1] - a[1]);
}

/* ---------- 渲染 ---------- */

function barRows(rows, total) {
  if (rows.length === 0) return '<p class="empty-hint">暂无数据</p>';
  return rows
    .map(([label, count]) => {
      const width = total === 0 ? 0 : Math.round((count / total) * 100);
      return (
        '<div class="bar-row">' +
        `<span>${escapeHtml(label)}</span>` +
        `<div class="bar-track"><div class="bar-fill" style="width:${width}%"></div></div>` +
        `<span>${count}</span>` +
        '</div>'
      );
    })
    .join('');
}

function renderBars(tasks, stats) {
  const container = $('#stats-bars');
  if (!container) return;

  const statusRows = STATUS_ORDER.map((status) => [
    STATUS_LABEL[status],
    tasks.filter((task) => task.status === status).length,
  ]).filter(([, count]) => count > 0);

  const projectNames = new Map(getProjects().map((project) => [String(project.id), project.name]));
  const projectRows = countBy(tasks, (task) => {
    if (!task.project_id) return '私人任务';
    return projectNames.get(String(task.project_id)) || '其他项目';
  });

  const memberNames = new Map(getMembers().map((member) => [String(member.id), member.name]));
  const memberRows = countBy(tasks, (task) => {
    if (!task.assignee_id) return UNSET;
    return memberNames.get(String(task.assignee_id)) || UNSET;
  });

  container.innerHTML =
    '<p class="group-title">按状态</p>' +
    barRows(statusRows, stats.total) +
    '<p class="group-title">按项目</p>' +
    barRows(projectRows, stats.total) +
    '<p class="group-title">按成员</p>' +
    barRows(memberRows, stats.total) +
    '<p class="group-title">完成率</p>' +
    '<div class="bar-row"><span>已完成</span>' +
    `<div class="bar-track"><div class="bar-fill" style="width:${stats.rate}%"></div></div>` +
    `<span>${stats.rate}%</span></div>`;
}

function renderTodayList(tasks) {
  const list = $('#stats-today');
  if (!list) return;
  const today = todayIso();
  const items = tasks
    .filter((task) => task.status !== 'done' && task.due_date === today)
    .sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0));
  if (items.length === 0) {
    list.innerHTML = '<p class="empty-hint">今天没有到期的任务</p>';
    return;
  }
  list.innerHTML = items
    .map(
      (task) =>
        '<li><button type="button" data-task-id="' + escapeHtml(task.id) + '">' +
        '<span class="swatch"></span>' +
        `${escapeHtml(task.title)}` +
        '<span class="count">今天</span>' +
        '</button></li>',
    )
    .join('');
}

function render() {
  const tasks = getTasks();
  const stats = compute(tasks);

  const todayCount = $('#stats-today-count');
  const overdueCount = $('#stats-overdue-count');
  const doneRate = $('#stats-done-rate');
  if (todayCount) todayCount.textContent = String(stats.todayDue.length);
  if (overdueCount) overdueCount.textContent = String(stats.overdue.length);
  if (doneRate) doneRate.textContent = `${stats.rate}%`;

  renderBars(tasks, stats);
  renderTodayList(tasks);
}

/* ---------- 交互 ---------- */

function openPanel() {
  const dialog = $('#stats-panel');
  if (!dialog) return;
  render();
  if (!dialog.open) dialog.showModal();
}

export async function init(ctx) {
  state.ctx = ctx;

  $('#stats-toggle')?.addEventListener('click', openPanel);

  $('#stats-today')?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-task-id]');
    if (!button) return;
    const task = getTasks().find((item) => String(item.id) === String(button.dataset.taskId));
    if (!task) return;
    $('#stats-panel')?.close();
    openEditor(task, {});
  });

  onTasksChanged(() => {
    // 面板开着就实时刷新，关着也刷一次，下次打开是热的。
    render();
  });

  render();
}
