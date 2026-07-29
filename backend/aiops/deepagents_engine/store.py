"""
DjangoORMStore — 基于 Django Cache 的 LangGraph BaseStore 实现。

用于跨会话持久化：
- 用户环境偏好（默认 knowledge environment）
- 常用查询模式（warm up fastpath）
- Zabbix hostid 缓存（避免重复 lookup）
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from django.core.cache import cache as django_cache

logger = logging.getLogger(__name__)

# 命名空间前缀，避免与其它缓存键冲突
STORE_PREFIX = "aiops:store"


class DjangoStore:
    """基于 Django Cache 的 LangGraph 持久化存储。

    所有数据以 namespace + key 组合为缓存键存入 Django Cache。
    支持 Redis / LocMem / Database 等所有 Django Cache 后端。

    使用方式：
        store = DjangoStore()
        store.put(("user_prefs",), "default_env", {"name": "prod"})
        value = store.get(("user_prefs",), "default_env")
    """

    def __init__(self, prefix: str = STORE_PREFIX, default_ttl: int = 86400):
        self._prefix = prefix
        self._default_ttl = default_ttl  # 默认 24 小时

    def _make_key(self, namespace: tuple[str, ...], key: str) -> str:
        """构建缓存键: aiops:store:{namespace1}/{namespace2}:{key}"""
        ns_path = "/".join(namespace) if namespace else "_root"
        return f"{self._prefix}:{ns_path}:{key}"

    def put(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: dict[str, Any],
        ttl: Optional[int] = None,
    ) -> None:
        """存储一个键值对。"""
        cache_key = self._make_key(namespace, key)
        timeout = ttl if ttl is not None else self._default_ttl
        try:
            django_cache.set(cache_key, json.dumps(value, ensure_ascii=False, default=str), timeout)
        except Exception as exc:
            logger.warning("DjangoStore put 失败 (%s): %s", cache_key, exc)

    def get(
        self,
        namespace: tuple[str, ...],
        key: str,
    ) -> Optional[dict[str, Any]]:
        """读取一个键值对。"""
        cache_key = self._make_key(namespace, key)
        try:
            raw = django_cache.get(cache_key)
            if raw is None:
                return None
            return json.loads(raw) if isinstance(raw, str) else raw
        except Exception as exc:
            logger.warning("DjangoStore get 失败 (%s): %s", cache_key, exc)
            return None

    def search(
        self,
        namespace: tuple[str, ...],
        *,
        filter: Optional[dict[str, Any]] = None,
        limit: int = 10,
    ) -> list[tuple[str, dict[str, Any]]]:
        """搜索命名空间下的所有条目（简化实现）。

        注意：LocMem 后端不支持 key 遍历，此方法在 locmem 下返回空列表。
        Redis 后端可通过 keys 模式匹配实现完整搜索。
        """
        ns_path = "/".join(namespace) if namespace else "_root"
        pattern = f"{self._prefix}:{ns_path}:*"

        results = []
        if not hasattr(django_cache, 'keys'):
            logger.warning("DjangoStore.search 需要 Redis 后端，当前后端不支持 keys() 操作")
            return results

        try:
            for full_key in django_cache.keys(pattern):
                    key_suffix = full_key.replace(f"{self._prefix}:{ns_path}:", "")
                    value = django_cache.get(full_key)
                    if value is not None:
                        item = json.loads(value) if isinstance(value, str) else value
                        # 基本过滤
                        if filter:
                            if not all(item.get(k) == v for k, v in filter.items()):
                                continue
                        results.append((key_suffix, item))
                        if len(results) >= limit:
                            break
        except Exception as exc:
            logger.debug("DjangoStore search 降级 (%s): %s", pattern, exc)

        return results

    def delete(self, namespace: tuple[str, ...], key: str) -> None:
        """删除一个键值对。"""
        cache_key = self._make_key(namespace, key)
        try:
            django_cache.delete(cache_key)
        except Exception as exc:
            logger.warning("DjangoStore delete 失败 (%s): %s", cache_key, exc)


# 全局单例
_store_instance: Optional[DjangoStore] = None


def get_store() -> DjangoStore:
    """获取全局 DjangoStore 单例。"""
    global _store_instance
    if _store_instance is None:
        _store_instance = DjangoStore()
    return _store_instance
