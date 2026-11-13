# 项目操作逻辑

登录 → 查询任务/统计 → Agent 提出创建或更新 → PendingAction → 用户确认 → 写入。所有任务按 owner_id 隔离，重复确认幂等。
