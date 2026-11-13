/**
 * 接口封装层（设计方案 §7.1 的 js/api.js，卓江城维护）。
 *
 * 只做三件事：
 *   1. 拼路径和查询串；
 *   2. 把请求交给 request.js（超时/重试/错误归一已在那边做过，这里不重复造）；
 *   3. 把列表响应归一化成 { items, total, truncated }（统一开发规范 §7）。
 *
 * 业务判断和 DOM 渲染一律留在各自模块里。路径与字段以 docs/api-contract.md 为准；
 * 契约落地前先按设计方案 §5 的路径写，未实现的接口会照常抛 ApiError（status 404），
 * 调用方按需降级——这里不吞错，否则联调时看不出后端漏了哪个接口。
 */
import { request } from '../request.js';

export { ApiError } from '../request.js';

/** 列表默认一次取 100 条，与设计方案 §5.1 的 limit 默认值一致。 */
const LIST_LIMIT = 100;

/** Agent 一轮最多走 6 步、每步一次模型调用，前端给足 60 秒。 */
const AGENT_TIMEOUT = 60000;

/** 最近 10 轮上下文，服务端不存会话（设计方案 §6.2 第 1 条）。 */
const HISTORY_LIMIT = 10;

/**
 * 把对象拼成查询串：跳过 null / undefined / 空串，数组按逗号拼接。
 * @param {Record<string, unknown>} params
 * @returns {string} 形如 `?status=todo&limit=100`，无参数时返回空串
 */
export function query(params = {}) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    if (Array.isArray(value)) {
      if (value.length === 0) continue;
      search.set(key, value.join(','));
      continue;
    }
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}

/**
 * 列表响应归一化。后端按规范回 { items, total, truncated }；
 * 现有 GET /api/tasks 只回 { items }，这里补出 total 和 truncated，前端不用两套写法。
 * @param {unknown} payload
 * @returns {{items: Array<Record<string, unknown>>, total: number, truncated: boolean}}
 */
export function asList(payload) {
  if (Array.isArray(payload)) {
    return { items: payload, total: payload.length, truncated: false };
  }
  const items = Array.isArray(payload && payload.items) ? payload.items : [];
  const total = Number.isFinite(payload && payload.total) ? payload.total : items.length;
  return { items, total, truncated: Boolean(payload && payload.truncated) };
}

/** 登录态相关：/api/auth/* */
export const auth = {
  /** @param {string} email @param {string} password */
  login(email, password) {
    return request('/api/auth/login', { method: 'POST', body: { email, password } });
  },

  logout() {
    return request('/api/auth/logout', { method: 'POST' });
  },

  /** @returns {Promise<{id: number, email: string, name: string}>} */
  me() {
    return request('/api/auth/me');
  },

  /** @param {{email: string, name: string, password: string}} payload */
  register(payload) {
    return request('/api/auth/register', { method: 'POST', body: payload });
  },
};

/** 任务相关：/api/tasks/* */
export const tasks = {
  /**
   * 任务列表。筛选键与设计方案 §5.1 对齐：
   * status / project_id / priority / tag / assignee_id / q / due(today|overdue|week) / limit / offset
   * @param {Record<string, unknown>} filters
   * @returns {Promise<{items: Array<Record<string, unknown>>, total: number, truncated: boolean}>}
   */
  async list(filters = {}) {
    const payload = await request(
      '/api/tasks' +
        query({
          status: filters.status,
          project_id: filters.project_id,
          priority: filters.priority,
          tag: filters.tag,
          assignee_id: filters.assignee_id,
          q: filters.q,
          due: filters.due,
          limit: filters.limit === undefined ? LIST_LIMIT : filters.limit,
          offset: filters.offset,
        }),
    );
    return asList(payload);
  },

  /** 创建：REST 层只强制 title 非空（项目/截止日期只对 Agent 强制，见设计方案 §5.1） */
  create(payload) {
    return request('/api/tasks', { method: 'POST', body: payload });
  },

  /**
   * 局部更新：title/description/status/priority/due_date/project_id/assignee_id/sort_order
   * @param {number|string} id @param {Record<string, unknown>} patch
   */
  update(id, patch) {
    return request(`/api/tasks/${id}`, { method: 'PATCH', body: patch });
  },

  /** @param {number|string} id */
  remove(id) {
    return request(`/api/tasks/${id}`, { method: 'DELETE' });
  },

  /** 今日待办：{ today: [], overdue: [], done_rate: number } */
  today() {
    return request('/api/tasks/today');
  },

  /** 统计：total / done / overdue，契约扩展后追加今日到期数与完成率 */
  stats() {
    return request('/api/tasks/stats');
  },
};

/** 项目相关：/api/projects/* */
export const projects = {
  /** @returns {Promise<{items: Array<Record<string, unknown>>, total: number, truncated: boolean}>} */
  async list() {
    return asList(await request('/api/projects'));
  },

  /** @param {{name: string, color?: string, description?: string}} payload */
  create(payload) {
    return request('/api/projects', { method: 'POST', body: payload });
  },

  /** @param {number|string} id @param {Record<string, unknown>} patch */
  update(id, patch) {
    return request(`/api/projects/${id}`, { method: 'PATCH', body: patch });
  },

  /**
   * 删除项目（仅 owner）。级联删任务的二次确认参数原样透传，
   * 具体键名以 docs/api-contract.md 的 projects 节为准，例如 { confirm_tasks: true }。
   * @param {number|string} id @param {Record<string, unknown>} params
   */
  remove(id, params = {}) {
    return request(`/api/projects/${id}` + query(params), { method: 'DELETE' });
  },

  /** 按状态、优先级分组计数 */
  stats(id) {
    return request(`/api/projects/${id}/stats`);
  },
};

/** 成员相关：/api/projects/{id}/members */
export const members = {
  /** @param {number|string} projectId */
  list(projectId) {
    return request(`/api/projects/${projectId}/members`);
  },

  /**
   * 按邮箱邀请（被邀者必须已注册，未注册 404、重复 409）
   * @param {number|string} projectId @param {{email: string, role?: string}} payload
   */
  invite(projectId, payload) {
    return request(`/api/projects/${projectId}/members`, { method: 'POST', body: payload });
  },

  /** 改角色：role ∈ {owner, member} */
  update(projectId, userId, patch) {
    return request(`/api/projects/${projectId}/members/${userId}`, {
      method: 'PATCH',
      body: patch,
    });
  },

  /** 移除成员（仅 owner） */
  remove(projectId, userId) {
    return request(`/api/projects/${projectId}/members/${userId}`, { method: 'DELETE' });
  },
};

/** 看板：一次取回四列卡片，减少首屏请求（设计方案 §5.2） */
export const board = {
  /** @param {number|string|undefined} projectId */
  get(projectId) {
    return request('/api/board' + query({ project_id: projectId }));
  },
};

/** Agent：/api/agent/* */
export const agent = {
  /**
   * 运行一轮。history 只带最近 10 轮，服务端保持无状态。
   * @param {string} question
   * @param {Array<{role: string, content: string}>} history
   */
  run(question, history = []) {
    return request('/api/agent/run', {
      method: 'POST',
      body: { question, history: history.slice(-HISTORY_LIMIT) },
      timeout: AGENT_TIMEOUT,
    });
  },

  /** 我的待确认列表（刷新页面不丢） */
  pending() {
    return request('/api/agent/pending');
  },

  /** 确认执行；重复确认幂等 */
  confirm(actionId) {
    return request('/api/agent/confirm', { method: 'POST', body: { action_id: actionId } });
  },

  /** 取消待确认操作，状态置 cancelled */
  cancel(actionId) {
    return request('/api/agent/cancel', { method: 'POST', body: { action_id: actionId } });
  },

  /** 服务端已注册的工具清单，前端只读用途 */
  tools() {
    return request('/api/agent/tools');
  },
};

const api = { auth, tasks, projects, members, board, agent, asList, query };

export default api;
