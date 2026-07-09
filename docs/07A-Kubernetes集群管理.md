# SxDevOps Kubernetes 集群管理

## 一、概述

SxDevOps 通过 Kubernetes API 接入集群，在平台内实现工作负载查看、Pod 管理、ConfigMap/Secret 浏览、容器日志查看和 Web 终端操作。

**前置条件：**
- Kubernetes 1.24+ 集群
- 平台能访问集群 API Server
- 有效的 kubeconfig 或 ServiceAccount Token
- 需要 `ops.k8s.view` / `ops.k8s.manage` 权限

## 二、平台端配置

### 2.1 进入页面

侧边栏：**容器管理 → K8s 集群**

### 2.2 添加集群

点击"新增集群"，填写配置：

| 字段 | 说明 |
|------|------|
| 集群名称 | 自定义名称，如 `生产集群` |
| API Server 地址 | 如 `https://k8s-api.example.com:6443` |
| 认证方式 | **Kubeconfig** 或 **ServiceAccount Token** |
| Kubeconfig | 粘贴 kubeconfig 文件内容 |
| Token | 粘贴 ServiceAccount Token |
| 跳过 TLS 验证 | 自签证书环境需勾选 |

### 2.3 连接验证

保存后，平台自动测试集群连通性。成功后显示集群版本和节点数量。

## 三、K8s 端要求

### 3.1 创建 ServiceAccount（推荐）

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: sxdevops
  namespace: default
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: sxdevops-reader
rules:
  - apiGroups: [""]
    resources: ["pods", "services", "configmaps", "secrets", "nodes", "namespaces", "persistentvolumeclaims"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets", "daemonsets"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["batch"]
    resources: ["jobs", "cronjobs"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["ingresses"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: sxdevops-reader
subjects:
  - kind: ServiceAccount
    name: sxdevops
    namespace: default
roleRef:
  kind: ClusterRole
  name: sxdevops-reader
  apiGroup: rbac.authorization.k8s.io
```

### 3.2 获取 Token

```bash
kubectl create token sxdevops -n default
```

### 3.3 需要写入权限时的额外配置

如果需要在平台内操作 K8s 资源（扩缩容、重启、修改配置等），需要扩展 ClusterRole 的 verbs 加入 `create`、`update`、`patch`、`delete`。

## 四、平台功能

配置集群后，可在 K8s 管理页面操作：

| Tab/功能 | 说明 |
|---------|------|
| 集群概览 | 节点状态、资源使用、命名空间列表 |
| 工作负载 | Deployment、StatefulSet、DaemonSet、Job、CronJob |
| Pod 管理 | Pod 列表、日志查看、Web 终端 |
| 服务与网络 | Service、Ingress |
| 存储 | PV、PVC、StorageClass |
| 配置 | ConfigMap、Secret |

## 五、验证

1. 添加集群并确认状态为"已连接"
2. 查看节点列表是否与 `kubectl get nodes` 一致
3. 点击某个 Pod → 查看日志 → 确认日志正常显示
4. 点击某个 Pod → Web 终端 → 确认能正常执行命令

## 六、安全建议

- 使用只读 ServiceAccount 进行日常运维
- 写入操作需要单独的高权限账号
- Secret 数据仅在查看时解密显示，列表页不显示敏感内容
- 建议通过防火墙限制 K8s API Server 仅允许平台 IP 访问
