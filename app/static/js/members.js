/**
 * 成员面板（设计方案 §7.1 js/members.js，付佳宝）：
 * 侧栏"项目成员"列表 + 成员弹窗——按邮箱邀请、切换角色、移除成员；
 * 另负责任务弹窗 #task-assignee 指派下拉的数据兜底（见 fillAssignee 注释）。
 *
 * 契约（docs/api-contract.md §3，戴罗轩）：
 *   - 邀请仅 owner；邮箱未注册 404、重复 409；改角色/移除仅 owner，非 owner 一律 404（防探测）
 *   - 不能移除 owner 角色、不能把最后一名 owner 降级（400）
 *   - 成员对象 {id(行id), user_id, email, name, role}——动作路径与指派一律用 user_id
 *
 * 项目归属：当前项目取公开 DOM #project-switcher（board.js 维护），并订阅 board 的
 * onTasksChanged 同步项目切换；成员变更后重新触发切换器 change 让 board 重载它的
 * state.members——只依赖公开交互，不改他人文件（红线②）。
 */
import api from './api.js';
import { getTasks, onTasksChanged } from './board.js';

let ctx = null;
let wired = false;

const state = {
  projectId: '',
  members: [],
  armedRemove: null,
  armedTimer: 0,
};

const $ = (selector) => document.querySelector(selector);

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
  if (ctx && typeof ctx.toast === 'function') ctx.toast(message);
}

function currentProjectId() {
  return ($('#project-switcher')?.value || '').trim() || state.projectId;
}

function meId() {
  const user = ctx && typeof ctx.getUser === 'function' ? ctx.getUser() : null;
  return user ? Number(user.id) : NaN;
}

function isOwner() {
  const id = meId();
  return state.members.some(
    (member) => Number(member.user_id) === id && member.role === 'owner',
  );
}

function roleLabel(role) {
  return role === 'owner' ? '负责人' : '成员';
}

/**
 * 让看板/统计重载任务与成员：board.js 没有对外的刷新出口，重新触发项目切换器的
 * change 事件即可走它自己的切换流程（见 board.js wireProjectSwitch）。
 */
function syncBoard() {
  const switcher = $('#project-switcher');
  if (switcher) switcher.dispatchEvent(new Event('change'));
}

/* ---------- 提示 ---------- */

function showError(message) {
  const el = $('#member-error');
  if (!el) {
    toast(message);
    return;
  }
  el.textContent = message;
  el.classList.remove('hidden');
}

function clearError() {
  const el = $('#member-error');
  if (!el) return;
  el.textContent = '';
  el.classList.add('hidden');
}

/* ---------- 数据与渲染 ---------- */

async function load() {
  const projectId = currentProjectId();
  if (!projectId) {
    state.members = [];
    renderSidebar();
    return [];
  }
  const payload = await api.members.list(projectId);
  state.members = (payload && payload.items) || [];
  renderSidebar();
  return state.members;
}

function renderSidebar() {
  const list = $('#member-list');
  const empty = $('#member-empty');
  if (list) {
    list.innerHTML = state.members
      .map(
        (member) =>
          `<li><span>${escapeHtml(member.name)}</span>` +
          `<span class="muted">${roleLabel(member.role)}</span></li>`,
      )
      .join('');
  }
  if (empty) {
    empty.classList.toggle('hidden', state.members.length > 0);
    empty.textContent = currentProjectId() ? '该项目还没有成员。' : '选择项目后显示成员。';
  }
}

function renderRows() {
  const rows = $('#member-rows');
  if (!rows) return;
  const manage = isOwner();
  rows.innerHTML = state.members
    .map((member) => {
      const userId = Number(member.user_id);
      const canRemove = manage && member.role !== 'owner';
      const roleSelect =
        `<select data-role-user="${userId}" ${manage ? '' : 'disabled'}>` +
        `<option value="member"${member.role === 'member' ? ' selected' : ''}>成员</option>` +
        `<option value="owner"${member.role === 'owner' ? ' selected' : ''}>负责人</option>` +
        '</select>';
      const removeButton = canRemove
        ? `<button class="btn btn-ghost" type="button" data-remove-user="${userId}">移除</button>`
        : '';
      return (
        '<li style="display:flex;gap:8px;align-items:center;justify-content:space-between">' +
        `<span><strong>${escapeHtml(member.name)}</strong> ` +
        `<span class="muted">${escapeHtml(member.email)}</span></span>` +
        `<span style="display:flex;gap:6px;align-items:center">${roleSelect}${removeButton}</span>` +
        '</li>'
      );
    })
    .join('');
}

async function reload() {
  await load();
  renderRows();
}

/* ---------- 动作 ---------- */

async function invite() {
  const projectId = currentProjectId();
  const email = ($('#member-email')?.value || '').trim();
  clearError();
  if (!projectId) {
    showError('请先选择项目（成员按项目划分）');
    return;
  }
  if (!email) {
    showError('请填写邮箱');
    return;
  }
  if (!isOwner()) {
    showError('只有负责人可以邀请成员');
    return;
  }
  const button = $('#member-invite');
  if (button) button.disabled = true;
  try {
    const created = await api.members.invite(projectId, { email });
    // 契约 §3.2 邀请只收 {email}、角色固定 member；弹窗里选了"负责人"就补一次改角色
    const wantRole = $('#member-role')?.value;
    if (wantRole === 'owner' && created && created.user_id) {
      await api.members.update(projectId, created.user_id, { role: 'owner' });
    }
    if ($('#member-email')) $('#member-email').value = '';
    toast('已邀请');
    await reload();
    syncBoard();
  } catch (error) {
    showError((error && error.message) || '邀请失败');
  } finally {
    if (button) button.disabled = false;
  }
}

async function changeRole(userId, role) {
  const projectId = currentProjectId();
  clearError();
  try {
    await api.members.update(projectId, userId, { role });
    toast('角色已更新');
    await reload();
    syncBoard();
  } catch (error) {
    showError((error && error.message) || '修改角色失败');
    await reload().catch(() => {}); // 失败回滚下拉显示
  }
}

async function removeMember(userId, button) {
  const projectId = currentProjectId();
  clearError();
  try {
    await api.members.remove(projectId, userId);
    toast('已移除');
    state.armedRemove = null;
    clearTimeout(state.armedTimer);
    await reload();
    syncBoard();
  } catch (error) {
    showError((error && error.message) || '移除失败');
    if (button) button.textContent = '移除';
    state.armedRemove = null;
    clearTimeout(state.armedTimer);
  }
}

function handleRowsClick(event) {
  const button = event.target.closest('[data-remove-user]');
  if (!button) return;
  const userId = Number(button.dataset.removeUser);
  // 与任务卡删除一致的"点两次"确认：原生 confirm 会阻塞渲染，也不便自动化
  if (state.armedRemove !== userId) {
    state.armedRemove = userId;
    button.textContent = '确认移除？';
    clearTimeout(state.armedTimer);
    state.armedTimer = setTimeout(() => {
      state.armedRemove = null;
      if (button.isConnected) button.textContent = '移除';
    }, 3000);
    return;
  }
  removeMember(userId, button);
}

function handleRowsChange(event) {
  const select = event.target.closest('[data-role-user]');
  if (!select) return;
  changeRole(Number(select.dataset.roleUser), select.value);
}

/* ---------- 指派下拉兜底（D2 交付项） ---------- */

/**
 * 任务弹窗打开后，用成员接口的真实 user_id 重新填一遍 #task-assignee。
 *
 * 为什么需要：task-card.js/board.js 的填充用的是成员行 id（project_members.id，
 * 见 members.py 的 _member_out），而 PATCH /api/tasks 的 assignee_id 校验的是
 * user_id（tasks.py 的 _check_assignee）——两者对非首位成员不相等，会 422/指错人。
 * 那两个文件归卓江城（红线②），故这里在弹窗打开后用正确数据兜底，改动只落本人文件。
 *
 * 防 mock 误伤（两道闸）：
 *   1) mock 任务带 assignee_name 且其名字在真实成员里查无此人（真实 board 响应没有
 *      assignee_name 字段）→ 保持原填充；
 *   2) 选项里一个真实成员名都没有（mock 成员名是五人姓名）→ 保持原填充。
 */
async function fillAssignee(taskId) {
  const select = $('#task-assignee');
  if (!select) return;
  const task = taskId
    ? (getTasks() || []).find((item) => String(item.id) === String(taskId))
    : null;
  const projectId = task ? task.project_id : currentProjectId();
  if (!projectId) return; // 私人任务/未选项目：保持"未指派"
  let payload;
  try {
    payload = await api.members.list(projectId);
  } catch {
    return; // 接口不可用时保留原填充，不比坏
  }
  const members = (payload && payload.items) || [];
  if (members.length === 0) return;
  if (
    task &&
    typeof task.assignee_name === 'string' &&
    task.assignee_name &&
    !members.some((member) => member.name === task.assignee_name)
  ) {
    return; // mock 数据，交还给原填充
  }

  const desired = task && task.assignee_id != null ? String(task.assignee_id) : '';
  const currentValues = new Set(
    [...select.options].map((option) => option.value).filter((value) => value !== ''),
  );
  const realValues = new Set(members.map((member) => String(member.user_id)));
  const subsetOfReal = [...currentValues].every((value) => realValues.has(value));
  // 已经是正确的一套（或已正确预选）就不动，避免和原填充互相覆盖
  if (desired && currentValues.has(desired) && subsetOfReal) return;
  if (!desired && subsetOfReal && currentValues.size === realValues.size) return;
  // 选项里连一个真实成员名都没有 → mock 演示数据，交还原填充
  if (currentValues.size > 0 && !optionLabelsMatch(select, members)) return;

  select.innerHTML = [{ value: '', label: '未指派' }]
    .concat(members.map((member) => ({ value: String(member.user_id), label: member.name })))
    .map(
      (option) =>
        `<option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>`,
    )
    .join('');
  select.value = desired;
}

/** 选项里是否至少有一个标签等于真实成员名（用来识别 mock 成员选项）。 */
function optionLabelsMatch(select, members) {
  const names = new Set(members.map((member) => member.name));
  return [...select.options].some((option) => names.has(option.textContent));
}

let filterFillTimer = 0;

/**
 * 筛选栏 #filter-assignee 的选项值同样要 user_id（同一处根因，board.js 归卓江城，
 * 红线②不改他文件）。他的过滤逻辑读的是选项值（readFilters → 按 assignee_id 比对），
 * 所以把选项值校正成真实 user_id，"按成员筛"就正确了。
 * board 每次刷新后调用；200ms 后再补一次，等他异步的 renderMemberOptions 落定。
 */
function fillFilterOptions() {
  const select = $('#filter-assignee');
  if (!select || state.members.length === 0) return;
  const realValues = new Set(state.members.map((member) => String(member.user_id)));
  const memberValues = [...select.options]
    .map((option) => option.value)
    .filter((value) => value !== '' && value !== 'me');
  // 已经是正确的一套就不动；一个真实成员名都没有（mock）也不动
  if (
    memberValues.length > 0 &&
    (memberValues.every((value) => realValues.has(value)) &&
      memberValues.length === realValues.size)
  ) {
    return;
  }
  if (memberValues.length > 0 && !optionLabelsMatch(select, state.members)) return;
  const current = select.value;
  select.innerHTML = ['<option value="">全部成员</option>', '<option value="me">仅看我</option>']
    .concat(
      state.members.map(
        (member) =>
          `<option value="${escapeHtml(String(member.user_id))}">${escapeHtml(member.name)}</option>`,
      ),
    )
    .join('');
  select.value = current === 'me' || realValues.has(current) ? current : '';
}

function scheduleFilterFill() {
  fillFilterOptions();
  clearTimeout(filterFillTimer);
  filterFillTimer = setTimeout(fillFilterOptions, 200);
}

/* ---------- 挂载 ---------- */

function openModal() {
  const dialog = $('#member-modal');
  if (!dialog) return;
  clearError();
  if ($('#member-rows')) $('#member-rows').innerHTML = '';
  dialog.showModal();
  if (!currentProjectId()) {
    showError('请先选择项目（成员按项目划分）');
    return;
  }
  reload().catch((error) => showError((error && error.message) || '加载成员失败'));
}

function wire() {
  $('#member-manage')?.addEventListener('click', openModal);
  $('#member-invite')?.addEventListener('click', invite);
  $('#member-rows')?.addEventListener('click', handleRowsClick);
  $('#member-rows')?.addEventListener('change', handleRowsChange);
  $('#member-email')?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      invite();
    }
  });

  // 指派下拉兜底：弹窗由卡片点击 / 列头 + 打开，原填充是同步的，这里异步覆盖必然在其后
  document.addEventListener('click', (event) => {
    const card = event.target.closest('.task-card');
    if (card) {
      fillAssignee(card.dataset.id);
      return;
    }
    if (event.target.closest('.column-add')) fillAssignee('');
  });
}

export function init(context) {
  ctx = context;
  if (!wired) {
    wired = true;
    wire();
    // board 每次刷新都会带上当前项目（含从"全部项目"切到具体项目）
    onTasksChanged((_tasks, info) => {
      state.projectId = (info && info.projectId) || '';
      load()
        .then(() => scheduleFilterFill())
        .catch(() => {});
    });
  }
  load()
    .then(() => scheduleFilterFill())
    .catch(() => {});
}
