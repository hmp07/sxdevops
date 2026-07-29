"""
DjangoCacheSaver — 基于 Django Cache 的 LangGraph Checkpointer 实现。

用于 Human-in-the-Loop 中断与恢复：
- 写操作确认（execute_platform_action）
- 长会话状态持久化
- 跨请求的 Agent 状态恢复

每个 thread_id 对应一个 AIOpsChatSession，checkpoint 存储最近的 agent 状态。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from django.core.cache import cache as django_cache

logger = logging.getLogger(__name__)

CHECKPOINT_PREFIX = "aiops:checkpoint"
DEFAULT_TTL = 3600  # 1 小时——足够覆盖长会话


class DjangoCacheSaver:
    """基于 Django Cache 的 LangGraph Checkpointer 兼容实现。

    提供 LangGraph checkpointer 所需的接口：
    - get_tuple / put / list / put_writes / delete_thread

    使用方式：
        checkpointer = DjangoCacheSaver(ttl=3600)
        agent = create_deep_agent(..., checkpointer=checkpointer)
    """

    def __init__(self, ttl: int = DEFAULT_TTL):
        self._ttl = ttl

    def _thread_key(self, thread_id: str) -> str:
        return f"{CHECKPOINT_PREFIX}:{thread_id}"

    def _checkpoint_key(self, thread_id: str, checkpoint_ns: str = "", checkpoint_id: str = "") -> str:
        cid = checkpoint_id or "latest"
        return f"{CHECKPOINT_PREFIX}:{thread_id}:{checkpoint_ns}:{cid}"

    def _serialize(self, obj: Any) -> str:
        return json.dumps(obj, ensure_ascii=False, default=str)

    def _deserialize(self, raw: Any) -> Any:
        if raw is None:
            return None
        return json.loads(raw) if isinstance(raw, str) else raw

    def get_tuple(self, config: dict) -> Optional[tuple]:
        """获取 checkpoint。"""
        thread_id = config.get("configurable", {}).get("thread_id", "default")
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id", "")

        key = self._checkpoint_key(thread_id, checkpoint_ns, checkpoint_id)
        try:
            raw = django_cache.get(key)
            if raw is None:
                return None
            return self._deserialize(raw)
        except Exception as exc:
            logger.warning("DjangoCacheSaver get 失败 (%s): %s", key, exc)
            return None

    def put(
        self,
        config: dict,
        checkpoint: dict,
        metadata: dict,
        new_versions: dict,
    ) -> dict:
        """存储 checkpoint。"""
        thread_id = config.get("configurable", {}).get("thread_id", "default")
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")
        checkpoint_id = checkpoint.get("id", "")

        # 构建可序列化的元组
        data = {
            "config": {k: v for k, v in config.items() if k != "configurable"},
            "checkpoint": checkpoint,
            "metadata": metadata,
            "parent_checkpoint_id": checkpoint.get("parent_checkpoint_id"),
        }

        try:
            # 写入命名 checkpoint
            if checkpoint_id:
                ckpt_key = self._checkpoint_key(thread_id, checkpoint_ns, checkpoint_id)
                django_cache.set(ckpt_key, self._serialize(data), timeout=self._ttl)

            # 更新 latest 指针
            latest_key = self._checkpoint_key(thread_id, checkpoint_ns, "")
            django_cache.set(latest_key, self._serialize(data), timeout=self._ttl)

            # 追加到 thread 的 checkpoint 列表
            thread_key = self._thread_key(thread_id)
            thread_data = django_cache.get(thread_key) or []
            if isinstance(thread_data, str):
                thread_data = json.loads(thread_data)
            thread_data.append({
                "checkpoint_id": checkpoint_id,
                "timestamp": time.time(),
                "metadata": {k: str(v)[:100] for k, v in metadata.items()} if metadata else {},
            })
            # 只保留最近 50 个
            thread_data = thread_data[-50:]
            django_cache.set(thread_key, self._serialize(thread_data), timeout=self._ttl * 24)
        except Exception as exc:
            logger.warning("DjangoCacheSaver put 失败 (%s): %s", thread_id, exc)

        return {}

    def put_writes(
        self,
        config: dict,
        writes: list[tuple],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """存储待执行的 writes（HITL 中断恢复用）。"""
        thread_id = config.get("configurable", {}).get("thread_id", "default")
        writes_key = f"{CHECKPOINT_PREFIX}:{thread_id}:writes:{task_id}"
        try:
            django_cache.set(writes_key, self._serialize(writes), timeout=self._ttl)
        except Exception as exc:
            logger.warning("DjangoCacheSaver put_writes 失败: %s", exc)

    def list(
        self,
        config: dict,
        *,
        filter: Optional[dict] = None,
        before: Optional[dict] = None,
        limit: int = 10,
    ) -> list[dict]:
        """列出 thread 下的 checkpoint 列表。"""
        thread_id = config.get("configurable", {}).get("thread_id", "default")
        thread_key = self._thread_key(thread_id)

        try:
            thread_data = django_cache.get(thread_key)
            if not thread_data:
                return []
            items = json.loads(thread_data) if isinstance(thread_data, str) else thread_data
            items = items[-limit:]  # 取最近 N 个
            return items
        except Exception as exc:
            logger.warning("DjangoCacheSaver list 失败: %s", exc)
            return []

    def delete_thread(self, thread_id: str) -> None:
        """清理一个 thread 的所有 checkpoint。"""
        thread_key = self._thread_key(thread_id)
        try:
            django_cache.delete(thread_key)
            # 无法遍历删除所有 checkpoint key（locmem 限制），
            # 依赖 TTL 自动过期清理
        except Exception as exc:
            logger.warning("DjangoCacheSaver delete_thread 失败: %s", exc)


# 全局单例
_checkpointer_instance: Optional[DjangoCacheSaver] = None


def get_checkpointer(ttl: int = DEFAULT_TTL) -> DjangoCacheSaver:
    """获取全局 DjangoCacheSaver 单例。"""
    global _checkpointer_instance
    if _checkpointer_instance is None:
        _checkpointer_instance = DjangoCacheSaver(ttl=ttl)
    return _checkpointer_instance
