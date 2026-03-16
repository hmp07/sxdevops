# AgDevOps 运维平台

基于 Django、Django REST framework、Channels 与 Vue 3 / Element Plus 的一体化运维平台，覆盖主机管理、CMDB、部署管理、容器管理、Nginx 管理、日志中心、告警中心、SQL 审计等常见运维场景。

## 核心能力

- 仪表盘：汇总主机、部署、日志、告警等关键指标
- 主机管理：主机纳管、连通性测试、WebShell 终端
- CMDB：CI 类型、配置项、资源树、拓扑、成本分析、优化建议、资源申请
- 部署管理：部署记录、状态跟踪、发布过程查询
- 容器管理：K8s 集群、Docker 环境、容器与镜像查看
- Nginx 管理：环境、证书、域名、路由与配置发布
- 日志中心：日志源管理、查询、收藏条件、趋势图
- SQL 审计：数据源、SQL 工单、只读查询
- 工具市场：预留扩展型运维工具能力

## RBAC 权限体系

项目已内置统一 RBAC 权限模型，后续新功能也应遵循同一套约束。

- 模型：用户、用户组、角色、权限字典
- 后端：统一在 `backend/rbac/registry.py` 注册权限，在 `backend/rbac/permissions.py` 做接口校验
- 前端：路由、侧边栏、页面按钮、敏感操作统一走 `frontend/src/stores/auth.js`
- WebSocket / WebShell：服务端二次校验，不依赖前端隐藏
- SPA 登录页：后端已支持前端路由回退，直接访问 `/login` 不再返回 404

### 已覆盖的权限范围

- 用户 / 用户组 / 角色 / 权限字典管理
- 主机、终端、部署、告警、日志、SQL 审计、服务市场
- CMDB、K8s、Docker、Nginx 的页面级与按钮级权限控制

### 演示账号

执行 `cd backend && python manage.py seed_data` 后，会自动补齐 RBAC 演示数据。默认密码均为 `Admin@123456`。

- `admin`
- `ops_demo`
- `dev_demo`
- `audit_demo`
- `viewer_demo`

## 快速启动

### 1. 启动后端

```bash
cd backend
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data
python -m daphne -b 0.0.0.0 -p 8000 agdevops.asgi:application
```

后端默认地址：`http://localhost:8000`

### 2. 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端默认地址：`http://localhost:3000`

## 常用命令

```bash
# 后端测试
cd backend && python manage.py test

# 初始化或刷新演示数据（包含 RBAC 演示账号）
cd backend && python manage.py seed_data

# 前端开发
cd frontend && npm run dev

# 前端生产构建
cd frontend && npm run build

# 前端本地预览
cd frontend && npm run preview
```

## 新功能接入权限的建议流程

1. 在 `backend/rbac/registry.py` 注册权限编码，并按需加入内置角色
2. 在后端 API 或 WebSocket 入口增加 RBAC 校验
3. 在 `frontend/src/router/index.js` 和 `frontend/src/layout/AppLayout.vue` 配置路由 / 菜单权限
4. 在页面内用 `useAuthStore().hasPermission(...)` 控制按钮、操作列和对话框
5. 提交前执行 `cd backend && python manage.py test` 与 `cd frontend && npm run build`

## 项目结构

```text
agdevops/
|- backend/
|  |- agdevops/                  # Django 配置
|  |- ops/                       # 仪表盘、主机、部署、日志、告警
|  |- cmdb/                      # CMDB、拓扑、成本、资源申请
|  |- marketplace/               # 工具市场
|  |- rbac/                      # RBAC 权限系统
|  |- sqlaudit/                  # SQL 审计
|  |- requirements.txt
|  `- manage.py
|- frontend/
|  |- src/api/                   # 前端 API 封装
|  |- src/components/            # 复用组件
|  |- src/layout/                # 布局与菜单
|  |- src/router/                # 路由配置
|  |- src/stores/                # Pinia store
|  `- src/views/                 # 页面视图
|- docs/
`- README.md
```

## 开发说明

- 当前默认配置面向本地开发：`DEBUG = True`、SQLite、开放 CORS
- `frontend/dist/`、`frontend/node_modules/`、`backend/__pycache__/`、`db.sqlite3` 为生成产物，不建议提交
- 使用 Daphne 运行后端时，修改 Python 代码后需要手动重启服务

## License

MIT
