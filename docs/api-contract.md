# 个人任务与项目看板 · API 契约

版本 **V0.3** ｜ 2026-11-13 ｜ 骨架：戴罗轩；tasks 节：程熙；agent 节：郑伟健

> 本文件是前后端联调的唯一接口事实源。改动先改本文件、群里同步、前端确认，再动代码。
> 本版已写全 projects / members / board / tasks / agent 五节。

---

## 0. 通用约定

| 项 | 约定 |
|---|---|
| 前缀 | 所有接口以 /api 开头 |
| 鉴权 | 除注册/登录/健康检查外，全部依赖 current_user；支持 Cookie 与 Authorization: Bearer <token> |
| 成功列表 | {"items": [...], "total": n, "truncated": bool} |
| 错误 | {"detail": "中文原因"}；权限不足/资源不存在统一 404，不返回 403 |
| 日期 | YYYY-MM-DD；时间 ISO8601，服务端 naive UTC |
| 字段 | JSON 一律 snake_case |
| 角色 | owner（项目所有者）/ member（普通成员） |

状态码：

| 码 | 含义 |
|---|---|
| 200 | 查询/更新成功 |
| 201 | 创建成功 |
| 204 | 删除成功，无 body |
| 400 | 参数合法但业务不允许（如未确认级联删除、移除 owner） |
| 401 | 未登录/凭证无效 |
| 404 | 资源不存在或无权访问（防探测） |
| 409 | 冲突（如重复邀请） |
| 422 | 请求字段校验失败 |

---

## 1. 任务接口（程熙负责，状态：已实现）

> 对应实现：`app/routers/tasks.py` + `app/schemas.py`，权限统一走 `app/permissions.py`；接口测试 12 条随 `tests/test_tasks_api.py` 合入 main。

| 方法 | 路径 | 请求 | 响应 | 错误 |
|---|---|---|---|---|
| GET | /api/tasks | query：status、project_id、priority、tag、assignee_id、q、due(today\|overdue\|week)、limit(默认 100，≤500)、offset | {items:[Task], total, truncated} | 401 |
| GET | /api/tasks/today | — | {today:[Task], overdue:[Task], done_rate} | 401 |
| GET | /api/tasks/stats | — | {total, done, overdue} | 401 |
| POST | /api/tasks | {title\*、description?、project_id?、priority?(low/medium/high)、due_date?(YYYY-MM-DD)、assignee_id?、tags?(≤10，自动去重去空白)} | Task，201 | 401 / 404(项目非成员) / 422 |
| PATCH | /api/tasks/{id} | 任意子集：{title?、description?、status?(todo/in_progress/blocked/done)、priority?、due_date?(null=清空)、project_id?(null=移出项目)、assignee_id?(null=取消)、sort_order?} | Task，200 | 401 / 404(越权) / 422 |
| DELETE | /api/tasks/{id} | — | 204 | 401 / 404(项目任务仅 owner 角色可删) |

校验要点：REST 只强制 title（三件套是 Agent 侧规则）；指派非项目成员 → 422；PATCH 用 `model_fields_set` 区分"未传"与"显式置 null"；换项目时原指派对象不在新项目则自动清空；状态置 done 写 `completed_at`、撤 done 清空。

Task 结构：

```json
{ "id": 1, "title": "...", "description": "", "status": "todo", "priority": "medium",
  "due_date": "2026-11-14", "project_id": 1, "assignee_id": null, "sort_order": 0.0,
  "completed_at": null, "created_at": "...", "updated_at": "...", "tags": ["python"] }
```

## 2. 项目接口（戴罗轩）

### 2.1 GET /api/projects

当前用户作为成员加入的全部项目。

响应：

~~~json
{
  "items": [
    {
      "id": 1,
      "name": "AI 学习",
      "color": "#4f7",
      "description": "课程项目",
      "role": "owner",
      "member_count": 2,
      "task_count": 5
    }
  ],
  "total": 1,
  "truncated": false
}
~~~

### 2.2 POST /api/projects

创建项目；创建者自动写入 project_members(role=owner)。

请求：

~~~json
{"name": "AI 学习", "color": "#4f7", "description": "课程项目"}
~~~

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| name | string | 是 | 1–120，去首尾空白后非空 |
| color | string | 否 | ≤20，默认空字符串 |
| description | string | 否 | ≤2000，默认空字符串 |

响应 201：同 2.1 的单个项目对象（role=owner，member_count=1）。

### 2.3 PATCH /api/projects/{id}

仅项目 owner 可改；只更新显式传入的字段。

请求（字段均可选）：

~~~json
{"name": "新名字", "color": "#2f6fed", "description": "新简介"}
~~~

响应 200：同 2.1 的单个项目对象。非 owner / 项目不存在 → 404。

> 说明：archived 字段依赖 app/models.py 增加列（程熙单点），本版暂不支持；增加后再补本节。

### 2.4 DELETE /api/projects/{id}?confirm=true

仅 owner 可删；会级联删除该项目下的任务。

| 参数 | 位置 | 说明 |
|---|---|---|
| confirm | query | 必须显式 true；缺省/false 返回 400 |

响应 204 无 body。非 owner → 404。

### 2.5 GET /api/projects/{id}/stats

项目成员可读。

响应：

~~~json
{
  "project_id": 1,
  "total": 5,
  "done_rate": 0.4,
  "by_status": {"todo": 2, "in_progress": 1, "blocked": 0, "done": 2},
  "by_priority": {"low": 1, "medium": 3, "high": 1},
  "member_count": 2
}
~~~

非成员/项目不存在 → 404。

---

## 3. 成员接口（戴罗轩）

### 3.1 GET /api/projects/{id}/members

项目成员可读成员列表。

响应：

~~~json
{
  "items": [
    {"id": 1, "user_id": 1, "email": "demo@tasks.dev", "name": "演示用户", "role": "owner"}
  ],
  "total": 1,
  "truncated": false
}
~~~

非成员/项目不存在 → 404。

### 3.2 POST /api/projects/{id}/members

仅 owner；按邮箱邀请已注册用户。

请求：

~~~json
{"email": "member@example.com"}
~~~

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| email | string | 是 | 3–120，服务端按小写匹配 |

响应 201：

~~~json
{"id": 2, "user_id": 2, "email": "member@example.com", "name": "成员", "role": "member"}
~~~

| 情况 | 状态码 |
|---|---|
| 邮箱未注册 | 404 |
| 已是项目成员 | 409 |
| 非 owner | 404 |

### 3.3 PATCH /api/projects/{id}/members/{user_id}

仅 owner；改角色。

请求：

~~~json
{"role": "owner"}
~~~

role 只能是 owner / member。响应 200：同 3.1 的单个成员对象。

规则：

- 不能把最后一名 owner 降为 member → 400；
- 目标不是项目成员 → 404；
- 非 owner 调用 → 404。

### 3.4 DELETE /api/projects/{id}/members/{user_id}

仅 owner；移除成员。

响应 204 无 body。

规则：不能移除 owner 角色 → 400；目标不存在 → 404；非 owner → 404。

---

## 4. 看板接口（戴罗轩）

### 4.1 GET /api/board?project_id=<id>

项目成员可读；一次返回四列卡片，供看板首屏渲染。

响应：

~~~json
{
  "project": {
    "id": 1, "name": "AI 学习", "color": "#4f7",
    "description": "", "role": "owner",
    "member_count": 2, "task_count": 5
  },
  "columns": {
    "todo": [
      {"id": 1, "title": "任务", "description": "", "status": "todo",
       "priority": "medium", "due_date": "2026-11-20", "assignee_id": null,
       "sort_order": 0, "tags": ["python"]}
    ],
    "in_progress": [], "blocked": [], "done": []
  }
}
~~~

非成员/项目不存在 → 404。

---

## 5. Agent 接口（郑伟健负责，状态：已实现）

> 对应实现：`app/routers/agent.py` + `app/tools.py` + `app/agent.py`；
> 用例 `tests/test_agent_tools.py`（8 条，全部 Fake LLM 离线）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/agent/tools | 模型可见的工具契约（8 个，公开不用登录） |
| POST | /api/agent/run | 跑一轮 Agent，返回答案 + 执行轨迹 + 待确认写操作 |
| GET | /api/agent/pending | 我的待确认列表（刷新页面不丢） |
| POST | /api/agent/confirm | 确认并执行，返回 diff；重复确认幂等 |
| POST | /api/agent/cancel | 拒绝待确认，状态置 cancelled |

### 5.1 POST /api/agent/run

请求：

~~~json
{
  "question": "把 Agent 练习移到进行中",
  "max_steps": 6,
  "history": [
    {"role": "user", "content": "我有哪些任务"},
    {"role": "assistant", "content": "你有 3 条任务：..."}
  ]
}
~~~

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| question | string | 是 | 2–20000 字 |
| max_steps | int | 否 | 1–10；服务端再按 `AGENT_MAX_STEPS` 夹一次，客户端传大无效 |
| history | array | 否 | 只取 user/assistant 纯文本，裁剪到最近 10 轮（20 条） |

响应 200：

~~~json
{
  "ok": true,
  "answer": "已准备好把「完成 Agent 练习」移到进行中，请确认。",
  "steps": [
    {"kind": "tool_call", "content": "{\"task_id\": 1}", "tool": "update_task", "args": {}, "ms": 0},
    {"kind": "tool_result", "content": "{\"action_id\": \"...\"}", "tool": "update_task", "args": null, "ms": 0},
    {"kind": "answer", "content": "已准备好...", "tool": null, "args": null, "ms": 0}
  ],
  "tool_calls": 1,
  "total_ms": 1200,
  "stopped_by": "answer",
  "pending_writes": [
    {
      "id": "action-uuid",
      "tool": "update_task",
      "args": {"task_id": 1, "status": "in_progress"},
      "before": {"id": 1, "status": "todo", "title": "完成 Agent 练习"},
      "after": {"id": 1, "status": "in_progress", "title": "完成 Agent 练习"},
      "expires_at": "2026-11-13T09:00:00"
    }
  ]
}
~~~

`stopped_by` ∈ `answer`（模型自然收敛）/ `max_steps`（撞上限）。

### 5.2 GET /api/agent/pending

只返回 `status=pending` 且未过期的记录；顺手把过期项标成 `expired`。

~~~json
{"items": [{"id": "...", "tool": "create_task", "args": {...}, "before": {}, "after": {...}, "expires_at": "...", "status": "pending"}], "total": 1, "truncated": false}
~~~

### 5.3 POST /api/agent/confirm

请求：`{"action_id": "..."}`；参数只存服务端，客户端改不了。

响应 200：

~~~json
{
  "ok": true,
  "tool": "update_task",
  "result": {
    "ok": true,
    "task_id": 1,
    "diff": {
      "before": {"status": "todo"},
      "after": {"status": "in_progress"},
      "changed": {"status": {"from": "todo", "to": "in_progress"}}
    }
  },
  "before": {"status": "todo"},
  "after": {"status": "in_progress"}
}
~~~

| 情况 | 状态码 |
|---|---|
| 待确认不存在 / 不属于当前用户 | 404 |
| 已执行（重复确认） | 200，返回首次结果（幂等） |
| 已取消 | 409 |
| 已过期 | 409 |
| 执行失败 | 500（状态回滚为 pending，可重试） |

### 5.4 POST /api/agent/cancel

请求：`{"action_id": "..."}`；响应为被取消的那条记录，`status=cancelled`。
重复取消返回同一状态；已执行的取消 → 409。

### 5.5 工具契约（8 个，读写分离）

| 工具 | 类型 | 关键参数 | 返回要点 |
|---|---|---|---|
| list_tasks | 读 | status/project_id/priority/tag/assignee_id/due_from/due_to/limit | items 含 project_name、assignee_name、tags；limit 夹在 1–50，超限 `truncated=true` |
| get_task | 读 | task_id | 全字段，供 diff 预览 |
| count_tasks | 读 | status/project_id/priority/assignee_id/due(today\|overdue\|week) | `{count}` |
| get_task_stats | 读 | — | total/done/overdue/due_today/done_rate/by_status/by_project/by_member |
| create_task | 写 | title+project_id+due_date **三件套必填**，另 description/priority/assignee_id/tags | 落待确认，不直接写库 |
| update_task | 写 | task_id + 任意可改字段 | 拦截前先取 `before` 快照 |
| list_projects | 读 | — | 当前用户参与的项目 + 角色 + 任务数 |
| list_members | 读 | project_id（可选） | 成员姓名/邮箱/角色；非成员调用报错 |

写工具（create_task / update_task）一律走确认流程；`AGENT_CONFIRM_WRITE=false` 时直接执行，仅供本地调试，不入仓库配置。

### 5.6 错误分级

| 情况 | 状态码 | detail |
|---|---|---|
| 未登录 | 401 | 请先登录 |
| 未配置 LLM 密钥 | 503 | 未配置 LLM 密钥，请联系管理员 |
| 上游超时 / 429 / 连接失败 | 502 | 模型服务暂不可用，请稍后重试 |
| 其他执行异常 | 500 | Agent 执行失败 |

对外不再回显上游原始报错（`§6.3` 要求）。

---

## 6. 修订记录

| 版本 | 日期 | 变更 |
|---|---|---|
| V0.1 | 2026-11-13 | 戴罗轩建骨架；写全 projects / members / board 三节；tasks、agent 留待对应负责人补齐 |
| V0.2 | 2026-11-13 | 补全 tasks 节（程熙） |
| V0.3 | 2026-11-13 | 补全 agent 节（郑伟健）：run/pending/cancel/confirm 契约、8 个工具、错误分级 |

