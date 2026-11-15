/**
 * 四列看板（设计方案 §7.1 的 js/board.js，卓江城维护）。
 *
 * 职责：把任务列表渲染成 todo/in_progress/blocked/done 四列，维护列计数与空态，
 * 并让顶栏的项目切换、筛选栏对当前数据生效；新建/编辑/删除的落库动作也在这里，
 * 弹窗本身交给 task-card.js（mountEditor）。
 *
 * 数据来源：D1 接口还没落地（设计方案 §8 卓江城那条写的是"先用契约字段 mock"），
 * 所以默认走 MOCK_TASKS。程熙的 GET /api/board 上线后，把下面 USE_MOCK 改成 false，
 * 或者直接删掉 mock 分支即可——渲染、计数、筛选的逻辑都不用动。
 *
 * D2 还要补：拖拽换列与列内排序（PATCH status / sort_order）。
 */
import api from './api.js';
import { cardHtml, mountEditor } from './task-card.js';

const USE_MOCK = false;  // 真机模式：/api/board D1 已上线（按本文件 L9 说明切换，验收10收口）

const COLUMNS = [
  { status: 'todo', title: '待办' },
  { status: 'in_progress', title: '进行中' },
  { status: 'blocked', title: '阻塞' },
  { status: 'done', title: '已完成' },
];

const MOCK_PROJECTS = [
  { id: 1, name: 'AI 学习', color: '#4f7f63' },
  { id: 2, name: '前端看板', color: '#b9741f' },
];

const MOCK_MEMBERS = [
  { id: 1, user_id: 1, name: '卓江城' },
  { id: 2, user_id: 2, name: '付佳宝' },
  { id: 3, user_id: 3, name: '程熙' },
  { id: 4, user_id: 4, name: '郑伟健' },
  { id: 5, user_id: 5, name: '戴罗轩' },
];

/** 按 design §4.2 的字段造数据：含 assignee/tags/sort_order，字段跟契约保持一致。 */
const MOCK_TASKS = [
  {
    id: 101,
    title: '补看板拖拽排序',
    description: '同列按 1024 步长插入，越界整列重排',
    status: 'todo',
    priority: 'high',
    due_date: isoDate(0),
    project_id: 2,
    project_name: '前端看板',
    assignee_id: 1,
    assignee_name: '卓江城',
    tags: ['前端', '看板'],
    sort_order: 1024,
  },
  {
    id: 102,
    title: '写 api-contract 的 tasks 节',
    description: '按设计方案 §5.1 列方法、字段与状态码',
    status: 'todo',
    priority: 'medium',
    due_date: isoDate(5),
    project_id: 1,
    project_name: 'AI 学习',
    assignee_id: 3,
    assignee_name: '程熙',
    tags: ['文档'],
    sort_order: 2048,
  },
  {
    id: 103,
    title: '完成任务筛选与分页',
    description: 'limit 默认 100，超出回 truncated=true',
    status: 'todo',
    priority: 'low',
    due_date: isoDate(-1),
    project_id: 2,
    project_name: '前端看板',
    assignee_id: 1,
    assignee_name: '卓江城',
    tags: ['接口'],
    sort_order: 3072,
  },
  {
    id: 201,
    title: '四列看板渲染',
    description: '先用契约字段 mock，联调后替换数据源',
    status: 'in_progress',
    priority: 'medium',
    due_date: isoDate(1),
    project_id: 2,
    project_name: '前端看板',
    assignee_id: 1,
    assignee_name: '卓江城',
    tags: ['前端'],
    sort_order: 1024,
  },
  {
    id: 202,
    title: 'Agent 工具三件套校验',
    description: 'title + project_id + due_date 缺一即拒绝',
    status: 'in_progress',
    priority: 'high',
    due_date: isoDate(2),
    project_id: 1,
    project_name: 'AI 学习',
    assignee_id: 4,
    assignee_name: '郑伟健',
    tags: ['Agent'],
    sort_order: 2048,
  },
  {
    id: 301,
    title: '成员邀请接口',
    description: '等戴罗轩的 members 节契约',
    status: 'blocked',
    priority: 'low',
    due_date: null,
    project_id: 2,
    project_name: '前端看板',
    assignee_id: 2,
    assignee_name: '付佳宝',
    tags: ['后端'],
    sort_order: 1024,
  },
  {
    id: 401,
    title: '环境自检六步',
    description: '3 passed、pip check 干净、health ok',
    status: 'done',
    priority: 'low',
    due_date: isoDate(-3),
    project_id: 1,
    project_name: 'AI 学习',
    assignee_id: 1,
    assignee_name: '卓江城',
    tags: ['环境'],
    sort_order: 1024,
  },
];

const state = {
  ctx: null,
  user: null,
  tasks: [],
  projects: [],
  members: [],
  projectId: '',
  filters: { priority: '', assignee: '', tag: '', q: '', due: '' },
};

/* ---------- 小工具 ---------- */

function isoDate(offsetDays) {
  const date = new Date();
  date.setDate(date.getDate() + offsetDays);
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${date.getFullYear()}-${month}-${day}`;
}

function daysFromToday(iso) {
  if (!iso) return null;
  const today = new Date(`${isoDate(0)}T00:00:00`);
  const target = new Date(`${iso}T00:00:00`);
  return Math.round((target - today) / 86400000);
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[char]);
}

/* ---------- 数据 ---------- */

async function loadTasks() {
  if (USE_MOCK) return MOCK_TASKS.map(decorateTask);
  if (state.projectId) {
    // 契约 §4.1：GET /api/board?project_id= 一次取回四列；兼容只回 {items:[...]} 的实现。
    const payload = await api.board.get(state.projectId);
    const rows = payload && payload.columns
      ? COLUMNS.flatMap((column) => payload.columns[column.status] || [])
      : api.asList(payload).items;
    await ensureMemberCache(rows);
    return rows.map(decorateTask);
  }
  // 看板快照是按项目取的（project_id 必填），没选项目时退回任务列表。
  const result = await api.tasks.list({ limit: 200 });
  await ensureMemberCache(result.items);
  return result.items.map(decorateTask);
}

async function loadProjects() {
  if (USE_MOCK) return MOCK_PROJECTS;
  return api.projects.list().then((result) => result.items);
}

async function loadMembers() {
  if (USE_MOCK) return MOCK_MEMBERS;
  if (!state.projectId) return [];
  // 契约 §3.1 回 {items, total, truncated}；不套 asList 直接 map 会 TypeError（付佳宝/戴罗轩都提过）。
  const rows = api.asList(await api.members.list(state.projectId)).items;
  memberCache.set(String(state.projectId), rows);
  return rows;
}

function projectName(projectId) {
  const project = state.projects.find((item) => Number(item.id) === Number(projectId));
  return project ? project.name : '';
}

/** 每个项目的成员表缓存：project_id -> 成员行（含 user_id/name），用于把 assignee_id 映射成姓名。 */
const memberCache = new Map();

/**
 * 服务端 Task / 看板卡片只回 assignee_id、不回 assignee_name（契约 §1、§4.1），
 * 卡片要显示指派人与项目名，这里用本地成员表补齐。
 * 拉成员要按项目来：先把涉及的项目成员拉一遍（有缓存），避免"全部项目"视图下徽标空白。
 */
async function ensureMemberCache(tasks) {
  const projectIds = new Set();
  tasks.forEach((task) => {
    const id = task.project_id != null ? String(task.project_id) : String(state.projectId || '');
    if (id) projectIds.add(id);
  });
  const missing = [...projectIds].filter((id) => !memberCache.has(id));
  await Promise.all(
    missing.map(async (id) => {
      try {
        memberCache.set(id, api.asList(await api.members.list(id)).items);
      } catch (error) {
        memberCache.set(id, []);
        console.warn('[board] 成员列表拉取失败：', id, error);
      }
    }),
  );
}

/** 成员唯一标识用 user_id（project_members.id 只在成员接口内部用，不能当 assignee_id）。 */
function findMember(projectId, userId) {
  if (!userId) return null;
  const cached = memberCache.get(String(projectId));
  const pool = cached && cached.length ? cached : state.members;
  return pool.find((item) => Number(item.user_id) === Number(userId)) || null;
}

function memberName(projectId, userId) {
  const member = findMember(projectId, userId);
  return member ? member.name : '';
}

function decorateTask(task) {
  // 看板卡片对象里没有 project_id（整列都属于该项目），用当前选中的项目补上，
  // 否则 matchFilters 的 project 判断会把卡片全滤掉（真机模式实测踩过）。
  const projectId = task.project_id != null ? task.project_id : state.projectId || null;
  const member = findMember(projectId, task.assignee_id);
  const project = state.projects.find((item) => Number(item.id) === Number(projectId));
  return {
    ...task,
    project_id: projectId,
    assignee_name: task.assignee_name || (member ? member.name : ''),
    project_name: task.project_name || (project ? project.name : ''),
  };
}

function nextMockId() {
  return MOCK_TASKS.reduce((max, task) => Math.max(max, Number(task.id) || 0), 0) + 1;
}

function nextSortOrder(status) {
  const orders = MOCK_TASKS.filter((task) => task.status === status).map(
    (task) => Number(task.sort_order) || 0,
  );
  return (orders.length ? Math.max(...orders) : 0) + 1024;
}

/**
 * 保存：mock 模式直接改内存里的 MOCK_TASKS，接真实接口时换成 api.tasks.create/update。
 * @param {{id: number|null, payload: Record<string, unknown>, mode: 'create'|'update'}} input
 */
async function saveTask({ id, payload, mode }) {
  if (USE_MOCK) {
    if (mode === 'create') {
      MOCK_TASKS.push({
        ...payload,
        id: nextMockId(),
        project_name: projectName(payload.project_id),
        assignee_name: memberName(payload.project_id, payload.assignee_id),
        sort_order: nextSortOrder(payload.status),
      });
    } else {
      const task = MOCK_TASKS.find((item) => Number(item.id) === Number(id));
      if (!task) throw new Error('任务不存在');
      Object.assign(task, payload, {
        project_name: projectName(payload.project_id),
        assignee_name: memberName(payload.project_id, payload.assignee_id),
      });
    }
  } else if (mode === 'create') {
    await api.tasks.create(payload);
  } else {
    await api.tasks.update(id, payload);
  }
  await refresh();
  state.ctx.toast(`${mode === 'create' ? '已创建' : '已保存'}${USE_MOCK ? '（mock 模式）' : ''}`);
}

/** @param {number} id */
async function deleteTask(id) {
  if (USE_MOCK) {
    const index = MOCK_TASKS.findIndex((item) => Number(item.id) === Number(id));
    if (index < 0) throw new Error('任务不存在');
    MOCK_TASKS.splice(index, 1);
  } else {
    await api.tasks.remove(id);
  }
  await refresh();
  state.ctx.toast(`已删除${USE_MOCK ? '（mock 模式）' : ''}`);
}

/* ---------- 筛选 ---------- */

function matchFilters(task) {
  if (state.projectId && Number(task.project_id) !== Number(state.projectId)) return false;
  const { priority, assignee, tag, q, due } = state.filters;
  if (priority && task.priority !== priority) return false;
  if (assignee === 'me' && Number(task.assignee_id) !== Number(state.user && state.user.id)) return false;
  if (assignee && assignee !== 'me' && Number(task.assignee_id) !== Number(assignee)) return false;
  if (tag && !(task.tags || []).includes(tag)) return false;
  if (q) {
    const haystack = `${task.title || ''} ${task.description || ''}`.toLowerCase();
    if (!haystack.includes(q.toLowerCase())) return false;
  }
  if (due) {
    const diff = daysFromToday(task.due_date);
    if (diff === null) return false;
    if (due === 'today' && diff !== 0) return false;
    if (due === 'overdue' && !(diff < 0 && task.status !== 'done')) return false;
    if (due === 'week' && !(diff >= 0 && diff <= 7)) return false;
  }
  return true;
}

function visibleTasks() {
  return state.tasks.filter(matchFilters);
}

/* ---------- 渲染 ---------- */

function renderColumn(column, tasks) {
  const body = document.querySelector(`.column-body[data-status="${column.status}"]`);
  if (!body) return;
  if (tasks.length === 0) {
    body.innerHTML = '<p class="empty-hint">暂无任务</p>';
    return;
  }
  body.innerHTML = tasks.map(cardHtml).join('');
}

function renderCounts(items) {
  COLUMNS.forEach((column) => {
    const count = items.filter((task) => task.status === column.status).length;
    const el = document.querySelector(`.column-count[data-count="${column.status}"]`);
    if (el) el.textContent = String(count);
  });
}

function renderBoard() {
  const items = visibleTasks();
  renderCounts(items);
  COLUMNS.forEach((column) => {
    const tasks = items
      .filter((task) => task.status === column.status)
      .sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0));
    renderColumn(column, tasks);
  });
}

/* ---------- 拖拽换列 / 列内排序 ---------- */

const SORT_STEP = 1024;

const dragState = {
  id: null,
  active: false,
  dropped: false,
};

function taskById(id) {
  return state.tasks.find((task) => String(task.id) === String(id)) || null;
}

function siblingCards(card) {
  const parent = card.parentElement;
  if (!parent) return { prev: null, next: null };
  const cards = [...parent.children].filter((el) => el.classList.contains('task-card'));
  const index = cards.indexOf(card);
  return {
    prev: index > 0 ? cards[index - 1] : null,
    next: index >= 0 && index < cards.length - 1 ? cards[index + 1] : null,
  };
}

function orderOf(card) {
  const task = card ? taskById(card.dataset.id) : null;
  return task ? Number(task.sort_order) || 0 : 0;
}

/**
 * 按 DOM 里的落点算新的 sort_order（§4.2：同列 1024 步长插入）。
 * 相邻两条之间没有空隙（差值 ≤ 1）时要求整列重排，避免浮点精度问题。
 */
function computeSortOrder(card) {
  const { prev, next } = siblingCards(card);
  const prevOrder = orderOf(prev);
  const nextOrder = orderOf(next);

  if (!prev && !next) return { sortOrder: SORT_STEP, renumber: false };
  if (!prev) {
    if (nextOrder > 1) return { sortOrder: Math.floor(nextOrder / 2), renumber: false };
    return { sortOrder: 0, renumber: true };
  }
  if (!next) return { sortOrder: prevOrder + SORT_STEP, renumber: false };
  if (nextOrder - prevOrder > 1) {
    return { sortOrder: Math.floor((prevOrder + nextOrder) / 2), renumber: false };
  }
  return { sortOrder: 0, renumber: true };
}

/** 越界时整列重排：按当前 DOM 顺序重新发号 1024、2048、3072…… */
function renumberColumn(status) {
  const body = document.querySelector(`.column-body[data-status="${status}"]`);
  if (!body) return;
  const cards = [...body.querySelectorAll('.task-card')];
  cards.forEach((card, index) => {
    const task = taskById(card.dataset.id);
    if (task) task.sort_order = (index + 1) * SORT_STEP;
  });
}

function clearDragStyles() {
  document.querySelectorAll('.task-card.is-dragging').forEach((el) => el.classList.remove('is-dragging'));
  document.querySelectorAll('.column-body.drag-over').forEach((el) => el.classList.remove('drag-over'));
}

function moveCardTo(event, body) {
  const dragging = document.querySelector('.task-card.is-dragging');
  if (!dragging) return;
  const hint = body.querySelector('.empty-hint');
  if (hint) hint.remove();
  const cards = [...body.querySelectorAll('.task-card')].filter((card) => card !== dragging);
  const after = cards.find((card) => {
    const rect = card.getBoundingClientRect();
    return event.clientY < rect.top + rect.height / 2;
  });
  if (after) body.insertBefore(dragging, after);
  else body.appendChild(dragging);
}

async function finishDrop(body) {
  const dragging = document.querySelector('.task-card.is-dragging');
  if (!dragging) return;
  const task = taskById(dragging.dataset.id);
  if (!task) return;

  const targetStatus = body.dataset.status;
  const { sortOrder, renumber } = computeSortOrder(dragging);
  const snapshot = { status: task.status, sort_order: task.sort_order };

  if (renumber) renumberColumn(targetStatus);
  task.status = targetStatus;
  if (!renumber) task.sort_order = sortOrder;

  // 没有实际变化就别发请求（拖回原位）
  if (!renumber && snapshot.status === task.status && snapshot.sort_order === task.sort_order) {
    renderBoard();
    return;
  }

  renderBoard();
  notifyTasksChanged();

  try {
    if (!USE_MOCK) {
      const payload = { status: task.status, sort_order: task.sort_order };
      await api.tasks.update(task.id, payload);
    }
  } catch (error) {
    task.status = snapshot.status;
    task.sort_order = snapshot.sort_order;
    renderBoard();
    notifyTasksChanged();
    state.ctx.toast(`移动失败，已还原：${error.message}`);
  }
}

function wireDragAndDrop() {
  const board = document.querySelector('#board');
  if (!board) return;

  board.addEventListener('dragstart', (event) => {
    const card = event.target.closest('.task-card');
    if (!card) return;
    dragState.id = card.dataset.id;
    dragState.active = true;
    dragState.dropped = false;
    card.classList.add('is-dragging');
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', String(card.dataset.id));
    }
  });

  board.addEventListener('dragover', (event) => {
    if (!dragState.active) return;
    const body = event.target.closest('.column-body');
    if (!body) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
    document
      .querySelectorAll('.column-body.drag-over')
      .forEach((el) => el.classList.toggle('drag-over', el === body));
    body.classList.add('drag-over');
    moveCardTo(event, body);
  });

  board.addEventListener('dragleave', (event) => {
    const body = event.target.closest('.column-body');
    if (!body) return;
    body.classList.remove('drag-over');
  });

  board.addEventListener('drop', async (event) => {
    if (!dragState.active) return;
    const body = event.target.closest('.column-body');
    if (!body) return;
    event.preventDefault();
    dragState.dropped = true;
    await finishDrop(body);
    dragState.active = false;
    clearDragStyles();
  });

  board.addEventListener('dragend', () => {
    // 拖到看板外面（没有 drop）时，DOM 已被 dragover 挪动过，重渲染回到数据顺序。
    if (dragState.active && !dragState.dropped) renderBoard();
    dragState.active = false;
    dragState.dropped = false;
    clearDragStyles();
  });
}


function renderProjects() {
  const select = document.querySelector('#project-switcher');
  if (!select) return;
  const options = ['<option value="">全部项目</option>'].concat(
    state.projects.map(
      (project) => `<option value="${escapeHtml(project.id)}">${escapeHtml(project.name)}</option>`,
    ),
  );
  select.innerHTML = options.join('');
  select.value = state.projectId;

  const list = document.querySelector('#project-list');
  if (!list) return;
  const empty = document.querySelector('#project-empty');
  if (empty) empty.classList.toggle('hidden', state.projects.length > 0);
  if (state.projects.length === 0) {
    list.innerHTML = '';
    return;
  }
  list.innerHTML = state.projects
    .map((project) => {
      const active = String(project.id) === String(state.projectId);
      return (
        `<li><button type="button" data-project="${escapeHtml(project.id)}" aria-current="${active}">` +
        `<span class="swatch" style="background:${escapeHtml(project.color || '#3f755b')}"></span>` +
        `${escapeHtml(project.name)}</button></li>`
      );
    })
    .join('');
}

/* ---------- 交互 ---------- */

function readFilters() {
  state.filters = {
    priority: document.querySelector('#filter-priority')?.value || '',
    assignee: document.querySelector('#filter-assignee')?.value || '',
    tag: document.querySelector('#filter-tag')?.value.trim() || '',
    q: document.querySelector('#filter-q')?.value.trim() || '',
    due: document.querySelector('#filter-due')?.value || '',
  };
}

function wireFilters() {
  ['#filter-priority', '#filter-assignee', '#filter-tag', '#filter-q', '#filter-due'].forEach(
    (selector) => {
      const el = document.querySelector(selector);
      if (!el) return;
      const event = el.tagName === 'SELECT' ? 'change' : 'input';
      el.addEventListener(event, () => {
        readFilters();
        renderBoard();
      });
    },
  );

  document.querySelector('#filter-reset')?.addEventListener('click', () => {
    ['#filter-priority', '#filter-assignee', '#filter-tag', '#filter-q', '#filter-due'].forEach(
      (selector) => {
        const el = document.querySelector(selector);
        if (el) el.value = '';
      },
    );
    readFilters();
    renderBoard();
  });
}

function wireProjectSwitch() {
  document.querySelector('#project-switcher')?.addEventListener('change', (event) => {
    state.projectId = event.target.value;
    renderProjects();
    loadMembers()
      .then((members) => {
        state.members = members;
        renderMemberOptions();
      })
      .catch(() => {});
    refresh().catch((error) => state.ctx.toast(error.message));
  });

  document.querySelector('#project-list')?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-project]');
    if (!button) return;
    state.projectId = button.dataset.project;
    renderProjects();
    refresh().catch((error) => state.ctx.toast(error.message));
  });

  // 项目 CRUD 是戴罗轩的 /api/projects，接口未落地前先如实提示，不做假的新建。
  document.querySelector('#project-new')?.addEventListener('click', () => {
    state.ctx.toast('项目新建等 /api/projects 接口落地后再接');
  });
}

/* ---------- 入口 ---------- */

export async function init(ctx) {
  state.ctx = ctx;
  state.user = ctx.user;

  wireFilters();
  wireProjectSwitch();

  state.projects = await loadProjects().catch(() => []);
  state.members = await loadMembers().catch(() => []);
  renderProjects();
  renderMemberOptions();

  mountEditor({
    getProjects: () => state.projects,
    getMembers: () => state.members,
    getTask: (id) => state.tasks.find((task) => String(task.id) === String(id)) || null,
    getDefaults: () => ({ projectId: state.projectId }),
    onSave: saveTask,
    onDelete: deleteTask,
  });

  wireDragAndDrop();

  await refresh();
}

async function refresh() {
  state.tasks = await loadTasks();
  renderTagOptions();
  renderBoard();
  notifyTasksChanged();
}

/* ---------- 给 stats.js 用的只读出口（避免两个模块互相 import） ---------- */

const taskListeners = new Set();

/** 任务列表变化时回调，stats.js 用它保持与看板一致。 */
export function onTasksChanged(handler) {
  if (typeof handler !== 'function') return () => {};
  taskListeners.add(handler);
  return () => taskListeners.delete(handler);
}

export function getTasks() {
  return state.tasks;
}

export function getProjects() {
  return state.projects;
}

export function getMembers() {
  return state.members;
}

function notifyTasksChanged() {
  taskListeners.forEach((handler) => {
    try {
      handler(state.tasks, { projectId: state.projectId });
    } catch (error) {
      console.error('[board] 任务变更回调失败', error);
    }
  });
}

/** 把 mock/真实成员填进筛选栏和弹窗的指派下拉（值统一用 user_id，与 tasks.assignee_id 同源）。 */
function renderMemberOptions() {
  const select = document.querySelector('#filter-assignee');
  if (!select) return;
  const current = select.value;
  select.innerHTML = ['<option value="">全部成员</option>', '<option value="me">仅看我</option>']
    .concat(
      state.members.map(
        (member) =>
          `<option value="${escapeHtml(member.user_id)}">${escapeHtml(member.name)}</option>`,
      ),
    )
    .join('');
  select.value = current;
}

/** 标签候选：从现有任务的标签里收集，供 #filter-tag 的 datalist 联想。 */
function renderTagOptions() {
  const datalist = document.querySelector('#tag-options');
  if (!datalist) return;
  const tags = Array.from(
    new Set(state.tasks.flatMap((task) => task.tags || []).filter(Boolean)),
  );
  datalist.innerHTML = tags.map((tag) => `<option value="${escapeHtml(tag)}"></option>`).join('');
}

