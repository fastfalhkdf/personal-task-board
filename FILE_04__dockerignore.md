# 文件开发记录：`.dockerignore`

> 目标文件：`.dockerignore`

## 开发者想法

负责个人任务看板业务，写操作必须确认并隔离用户。

## 完整代码

````text
.git
.gitignore
.env
.venv
__pycache__
*.pyc
*.db
data/*.db
data/*.db-*
tests/__pycache__
.DS_Store
````

验证：3 个测试通过。
