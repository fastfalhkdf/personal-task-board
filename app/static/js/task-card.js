/**
 * 任务卡与编辑弹窗（设计方案 §7.1 的 js/task-card.js，卓江城维护）。
 *
 * 这个文件只管"长什么样"和"表单怎么填/怎么校验"：
 *   - cardHtml(task)：看板卡片 HTML，board.js 复用它渲染四列；
 *   - mountEditor({...})：给卡片、列头 + 号、弹窗里的保存/删除接线。
 *
 * 数据从哪来、保存到哪去由 board.js 注入（getTask / onSave / onDelete），
 * 两个文件不互相 import，避免循环依赖。
 *
 * 删除用"点两次"确认，不用 window.confirm —— 原生弹窗会阻塞渲染进程，也没法自动化验证。
 */
export const PRIORITY_LABEL = { high: '高', medium: '中', low: '低' };
export const STATUS_LABEL = { todo: '待办', in_progress: '进行中', blocked: '阻塞', done: '已完成' };

const STATUSES = Object.keys(STATUS_LABEL);
const PRIORITIES = Object.keys(PRIORITY_LABEL);
const DUE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

const $ = (selector) => document.querySelector(selector);

let handlers = null;
let deleteArmed = false;
let deleteTimer = 0;

/* ---------- 展示用的小工具 ---------- */

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[char]);
}

function isoToday(offsetDays = 0) {
  const date = new Date();
  date.setDate(date.getDate() + offsetDays);
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${date.getFullYear()}-${month}-${day}`;
}

function daysFromToday(iso) {
  if (!iso) return null;
  const today = new Date(`${isoToday(0)}T00:00:00`);
  const target = new Date(`${iso}T00:00:00`);
  return Math.round((target - today) / 86400000);
}

function dueLabel(task) {
  const diff = daysFromToday(task.due_date);
  if (diff === null) return { text: '', overdue: false };
  if (task.status === 'done') return { text: `${task.due_date.slice(5)} 完成`, overdue: false };
  if (diff < 0) return { text: `逾期 ${Math.abs(diff)} 天`, overdue: true };
  if (diff === 0) return { text: '今天到期', overdue: true };
  if (diff === 1) return { text: '明天到期', overdue: false };
  if (diff <= 7) return { text: `${diff} 天后`, overdue: false };
  return { text: task.due_date.slice(5), overdue: false };
}

/* ---------- 卡片 ---------- */

export function cardHtml(task) {
  const due = dueLabel(task);
  const priority = PRIORITY_LABEL[task.priority] || '中';
  const tags = (task.tags || [])
    .map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`)
    .join('');
  const assignee = task.assignee_name
    ? `<span class="assignee" title="指派给 ${escapeHtml(task.assignee_name)}">${escapeHtml(task.assignee_name.slice(0, 1))}</span>`
    : '';
  const dueHtml = due.text
    ? `<span class="due${due.overdue ? ' is-overdue' : ''}">${escapeHtml(due.text)}</span>`
    : '';
  const description = task.description ? `<p>${escapeHtml(task.description)}</p>` : '';
  return (
    `<article class="task-card" data-id="${escapeHtml(task.id)}" role="listitem" tabindex="0" draggable="true">` +
    `<h3>${escapeHtml(task.title)}</h3>` +
    description +
    '<div class="task-meta">' +
    `<span class="badge-priority is-${escapeHtml(task.priority || 'medium')}">${priority}</span>` +
    dueHtml +
    tags +
    assignee +
    '</div></article>'
  );
}

/* ---------- 弹窗 ---------- */

function setValue(selector, value) {
  const el = $(selector);
  if (el) el.value = value == null ? '' : String(value);
}

function setText(selector, text) {
  const el = $(selector);
  if (el) el.textContent = text;
}

function fillSelect(selector, options, current) {
  const select = $(selector);
  if (!select) return;
  select.innerHTML = options
    .map((option) => `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`)
    .join('');
  select.value = current == null ? '' : String(current);
  if (select.value !== String(current == null ? '' : current)) select.value = '';
}

export function clearError() {
  const el = $('#task-error');
  if (!el) return;
  el.textContent = '';
  el.classList.add('hidden');
}

export function showError(message) {
  const el = $('#task-error');
  if (!el) return;
  el.textContent = message;
  el.classList.remove('hidden');
}

function setBusy(busy) {
  const save = $('#task-save');
  const remove = $('#task-delete');
  if (save) save.disabled = busy;
  if (remove) remove.disabled = busy;
}

function resetDeleteButton() {
  const button = $('#task-delete');
  deleteArmed = false;
  clearTimeout(deleteTimer);
  deleteTimer = 0;
  if (!button) return;
  button.textContent = '删除';
  button.classList.remove('is-armed');
}

function armDeleteButton() {
  const button = $('#task-delete');
  deleteArmed = true;
  if (!button) return;
  button.textContent = '确认删除？';
  button.classList.add('is-armed');
  clearTimeout(deleteTimer);
  deleteTimer = setTimeout(resetDeleteButton, 3000);
}

export function closeEditor() {
  const dialog = $('#task-modal');
  if (dialog && dialog.open) dialog.close();
}

/**
 * 打开弹窗。task 为空表示新建，defaultStatus 决定落在哪一列。
 */
export function openEditor(task, { defaultStatus = 'todo' } = {}) {
  const dialog = $('#task-modal');
  if (!dialog) return;

  const editing = Boolean(task && task.id !== undefined && task.id !== null && task.id !== '');
  const defaults = handlers && typeof handlers.getDefaults === 'function' ? handlers.getDefaults() : {};
  const projects = (handlers && handlers.getProjects()) || [];
  const members = (handlers && handlers.getMembers()) || [];

  setText('#task-modal-title', editing ? '编辑任务' : '新建任务');
  setValue('#task-id', editing ? task.id : '');
  setValue('#task-title', editing ? task.title || '' : '');
  setValue('#task-description', editing ? task.description || '' : '');

  fillSelect(
    '#task-project',
    [{ value: '', label: '私人任务（不挂项目）' }].concat(
      projects.map((project) => ({ value: project.id, label: project.name })),
    ),
    editing ? task.project_id : defaults.projectId || '',
  );
  fillSelect(
    '#task-status',
    STATUSES.map((status) => ({ value: status, label: STATUS_LABEL[status] })),
    editing ? task.status : defaultStatus,
  );
  fillSelect(
    '#task-priority',
    PRIORITIES.map((priority) => ({ value: priority, label: PRIORITY_LABEL[priority] })),
    editing ? task.priority : 'medium',
  );
  setValue('#task-due-date', editing ? task.due_date || '' : '');
  fillSelect(
    '#task-assignee',
    [{ value: '', label: '未指派' }].concat(
      // 指派值用 user_id：PATCH /api/tasks 校验的是 ProjectMember.user_id（契约 §1/§3.1）
      members.map((member) => ({ value: member.user_id, label: member.name })),
    ),
    editing ? task.assignee_id : '',
  );
  setValue('#task-tags', editing ? (task.tags || []).join(', ') : '');

  clearError();
  resetDeleteButton();
  const remove = $('#task-delete');
  if (remove) remove.classList.toggle('hidden', !editing);

  dialog.showModal();
  $('#task-title')?.focus();
}

/**
 * 读表单。返回 { id, payload, errors }，errors 非空就不要提交。
 * payload 的键与设计方案 §5.1 的 PATCH 字段对齐。
 */
export function readEditor() {
  const id = ($('#task-id')?.value || '').trim();
  const projectValue = $('#task-project')?.value || '';
  const assigneeValue = $('#task-assignee')?.value || '';
  const dueDate = ($('#task-due-date')?.value || '').trim();
  const tags = ($('#task-tags')?.value || '')
    .split(/[,，]/)
    .map((tag) => tag.trim())
    .filter(Boolean)
    .slice(0, 5);

  const payload = {
    title: ($('#task-title')?.value || '').trim(),
    description: ($('#task-description')?.value || '').trim(),
    status: $('#task-status')?.value || 'todo',
    priority: $('#task-priority')?.value || 'medium',
    due_date: dueDate || null,
    project_id: projectValue ? Number(projectValue) : null,
    assignee_id: assigneeValue ? Number(assigneeValue) : null,
    tags,
  };

  const errors = [];
  if (!payload.title) errors.push('标题不能为空');
  if (!PRIORITIES.includes(payload.priority)) errors.push('优先级不合法');
  if (!STATUSES.includes(payload.status)) errors.push('状态不合法');
  if (payload.due_date && !DUE_PATTERN.test(payload.due_date)) {
    errors.push('截止日期格式应为 YYYY-MM-DD');
  }
  if (payload.due_date && Number.isNaN(new Date(`${payload.due_date}T00:00:00`).getTime())) {
    errors.push('截止日期不是合法日期');
  }

  return { id: id ? Number(id) : null, payload, errors };
}

/* ---------- 接线 ---------- */

async function handleSubmit(event) {
  if (event) event.preventDefault();
  const { id, payload, errors } = readEditor();
  if (errors.length > 0) {
    showError(errors[0]);
    return;
  }
  setBusy(true);
  try {
    await handlers.onSave({ id, payload, mode: id ? 'update' : 'create' });
    closeEditor();
  } catch (error) {
    showError((error && error.message) || '保存失败');
  } finally {
    setBusy(false);
  }
}

async function handleDelete() {
  const id = Number($('#task-id')?.value || 0);
  if (!id) return;
  if (!deleteArmed) {
    armDeleteButton();
    return;
  }
  resetDeleteButton();
  setBusy(true);
  try {
    await handlers.onDelete(id);
    closeEditor();
  } catch (error) {
    showError((error && error.message) || '删除失败');
  } finally {
    setBusy(false);
  }
}

function handleDocumentClick(event) {
  const card = event.target.closest('.task-card');
  if (card) {
    openEditor(handlers.getTask(card.dataset.id), {});
    return;
  }
  const add = event.target.closest('.column-add');
  if (add) {
    openEditor(null, { defaultStatus: add.dataset.add || 'todo' });
  }
}

/**
 * @param {{
 *   getProjects: () => Array<{id: number, name: string}>,
 *   getMembers: () => Array<{id: number, name: string}>,
 *   getTask: (id: string) => Record<string, unknown> | null,
 *   getDefaults?: () => {projectId?: string},
 *   onSave: (input: {id: number|null, payload: object, mode: 'create'|'update'}) => Promise<void>,
 *   onDelete: (id: number) => Promise<void>,
 * }} options
 */
export function mountEditor(options) {
  handlers = options;
  document.addEventListener('click', handleDocumentClick);
  $('#task-form')?.addEventListener('submit', handleSubmit);
  $('#task-delete')?.addEventListener('click', handleDelete);
  $('#task-modal')?.addEventListener('close', resetDeleteButton);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && event.target === $('#task-title')) handleSubmit(event);
  });
}
