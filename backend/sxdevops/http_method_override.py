"""HTTP 方法覆盖中间件 — 兼容生产安全设备对 DELETE/PUT/PATCH 的阻断。

生产网络常见安全设备（WAF/网关/负载均衡）会丢弃 DELETE/PUT/PATCH 等
"危险方法"请求（请求根本不到达应用，无访问日志）。前端统一将这类请求
转换为 POST 并携带 X-HTTP-Method-Override 头（见 frontend/src/api/request.js），
本中间件在 URL 路由解析之前把 request.method 还原为原始方法，
使 DRF 路由、权限与视图按原始语义执行——与直接发送原方法完全等价。

安全边界（收窄后）：
  - 仅当原始方法为 POST 时才应用覆盖：无法借本机制篡改其它方法的语义
    （如把 DELETE 改写为 GET），杜绝任意动词篡改
  - 覆盖只影响"路由到哪个视图动作"；认证（Token）与 RBAC 由目标视图
    照常执行，覆盖后的请求与直接发送原方法经受完全相同的鉴权
  - 仅接受白名单内的方法
  - 该机制的存在前提是生产网络设备阻断原方法（用户明确要求 POST 方案）；
    若环境无此限制，前端发送的仍是标准方法，本中间件为空操作
"""

ALLOWED_METHODS = {'GET', 'POST', 'OPTIONS', 'DELETE', 'PUT', 'PATCH'}


class HttpMethodOverrideMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method != 'POST':
            return self.get_response(request)
        override = request.headers.get('X-HTTP-Method-Override', '').strip().upper()
        if override in ALLOWED_METHODS and override != 'POST':
            request.method = override
        return self.get_response(request)
