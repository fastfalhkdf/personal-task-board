# 文件开发记录：`.gitignore`

> 目标文件：`.gitignore`

## 开发者想法

负责个人任务看板业务，写操作必须确认并隔离用户。

## 完整代码

````text
.env
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
data/*.db
data/*.db-*
*.log
.DS_Store
````

验证：3 个测试通过。
