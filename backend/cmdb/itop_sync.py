"""iTop 数据同步引擎 — 将 iTop CMDB/工单数据批量同步到本地模型."""
import json
import logging
import requests
from django.utils.timezone import now
from cmdb.models import CIType, ConfigItem, CIRelation, iTopDataSource
from ops.models import TransactionTicket


# 默认 iTop CI 类到 SxDevOps CIType 的映射
DEFAULT_CI_CLASS_MAP = {
    'Server': '云主机(ECS)',
    'VirtualMachine': '虚拟机',
    'NetworkDevice': '网络设备',
    'StorageSystem': '存储系统',
    'ApplicationSolution': '应用方案',
    'WebApplication': 'Web应用',
    'WebServer': 'Web服务器',
    'DBServer': '数据库服务器',
    'Hypervisor': '虚拟化平台',
    'BusinessProcess': '业务流程',
}

# 默认工单类名
DEFAULT_TICKET_CLASSES = ['UserRequest', 'Incident', 'NormalChange', 'Problem']

# 工单类型映射
TICKET_TYPE_MAP = {
    'UserRequest': TransactionTicket.TYPE_CHANGE,
    'Incident': TransactionTicket.TYPE_INCIDENT,
    'NormalChange': TransactionTicket.TYPE_CHANGE,
    'Problem': TransactionTicket.TYPE_INCIDENT,
}


def _call_itop_api(ds, json_data):
    """调用 iTop REST API（同步引擎独立实现，不依赖 MCP Server）"""
    try:
        resp = requests.post(
            ds.api_url,
            data={
                'version': ds.api_version,
                'auth_user': ds.auth_user,
                'auth_pwd': ds.auth_password,
                'json_data': json_data,
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        return {'code': -1, 'message': str(e)}


def test_connection(ds):
    """测试 iTop 连接"""
    result = _call_itop_api(ds, json.dumps({
        'operation': 'core/check_credentials',
        'user': ds.auth_user,
        'password': ds.auth_password,
    }))
    return result.get('authorized', False) and result.get('code') == 0


def sync_ci_classes(ds):
    """同步 CI 类 → CIType（创建缺失的类型）"""
    class_map = ds.config.get('ci_class_map', DEFAULT_CI_CLASS_MAP) if ds.config else DEFAULT_CI_CLASS_MAP
    created = 0
    for _, ci_type_name in class_map.items():
        _, is_new = CIType.objects.get_or_create(
            name=ci_type_name,
            defaults={'description': f'从 iTop 同步的 {ci_type_name}'},
        )
        if is_new:
            created += 1
    return {'created': created, 'total': len(class_map)}


def sync_cis(ds):
    """全量同步 CI → ConfigItem"""
    class_map = ds.config.get('ci_class_map', DEFAULT_CI_CLASS_MAP) if ds.config else DEFAULT_CI_CLASS_MAP
    ci_classes = ds.config.get('ci_classes', list(class_map.keys())) if ds.config else list(class_map.keys())
    stats = {'created': 0, 'updated': 0, 'skipped': 0}

    for itop_class in ci_classes:
        if itop_class not in class_map:
            continue
        result = _call_itop_api(ds, '{"operation":"core/get","class":"%s","key":"SELECT %s","output_fields":"*"}' % (
            itop_class, itop_class
        ))
        if result.get('code') != 0:
            stats['skipped'] += 1
            continue

        ci_type, _ = CIType.objects.get_or_create(name=class_map[itop_class])
        objects = (result.get('objects') or {})
        for key, obj in objects.items():
            if obj.get('code') != 0:
                continue
            fields = obj.get('fields', {})
            name = fields.get('name') or fields.get('friendlyname') or key
            obj_key = obj.get('key')
            if not obj_key:
                stats['skipped'] += 1
                continue
            external_id = f'itop:{itop_class}:{obj_key}'

            # ApplicationSolution 的业务线设为自身名称
            if itop_class == 'ApplicationSolution':
                bl = name
            else:
                bl = fields.get('org_name', '') or ds.organization or ''

            defaults = {
                'ci_type': ci_type,
                'business_line': bl,
                'environment': 'prod',
                'admin_user': '',
                'status': _map_itop_status(fields.get('status', '')),
                'itop_datasource': ds,
                'external_id': external_id,
                'attributes': {
                    k: v for k, v in fields.items()
                    if k not in ('id', 'name', 'friendlyname', 'status', 'org_name')
                },
            }

            ci, created = ConfigItem.objects.update_or_create(
                external_id=external_id,
                defaults={**defaults, 'name': name},
            )
            if created:
                stats['created'] += 1
            else:
                stats['updated'] += 1

            # 触发设备关联匹配
            try:
                from ops.device_matcher import match_ci_to_zabbix
                match_ci_to_zabbix(ci)
            except Exception as e:
                logging.getLogger(__name__).warning('match_ci_to_zabbix failed for CI %s: %s', name, e)

    return stats


def sync_relations(ds):
    """同步 CI 关系 → CIRelation"""
    class_map = ds.config.get('ci_class_map', DEFAULT_CI_CLASS_MAP) if ds.config else DEFAULT_CI_CLASS_MAP
    ci_classes = ds.config.get('ci_classes', list(class_map.keys())) if ds.config else list(class_map.keys())
    relation_types = ds.config.get('relation_types', ['impacts']) if ds.config else ['impacts']
    stats = {'created': 0, 'skipped': 0}

    for itop_class in ci_classes:
        result = _call_itop_api(ds, '{"operation":"core/get","class":"%s","key":"SELECT %s","output_fields":"id"}' % (
            itop_class, itop_class
        ))
        if result.get('code') != 0:
            continue

        for key, obj in (result.get('objects') or {}).items():
            obj_id = obj.get('key')
            if not obj_id:
                continue
            for rel_type in relation_types:
                rel_result = _call_itop_api(ds,
                    '{"operation":"core/get_related","class":"%s","key":%s,"relation":"%s","depth":1,"direction":"down"}' % (
                        itop_class, obj_id, rel_type
                    ))
                if rel_result.get('code') != 0:
                    continue
                relations = rel_result.get('relations') or {}
                if isinstance(relations, list):
                    # iTop returns relations as a flat list; treat source==obj, target from list
                    for rel in relations:
                        src_key = key
                        src_ci = _ensure_ci_from_itop(src_key, ds)
                        if not src_ci:
                            continue
                        tgt_key = rel.get('key', '')
                        tgt_ci = _ensure_ci_from_itop(tgt_key, ds)
                        if not tgt_ci:
                            continue
                        _, created = CIRelation.objects.get_or_create(
                            source=src_ci,
                            target=tgt_ci,
                            relation_type=_map_relation_type(rel_type),
                        )
                        if created:
                            stats['created'] += 1
                        else:
                            stats['skipped'] += 1
                else:
                    for src_key, targets in relations.items():
                        src_ci = _ensure_ci_from_itop(src_key, ds)
                        if not src_ci:
                            continue
                        for target in (targets if isinstance(targets, list) else [targets]):
                            tgt_key = target.get('key', '')
                            tgt_ci = _ensure_ci_from_itop(tgt_key, ds)
                            if not tgt_ci:
                                continue
                            _, created = CIRelation.objects.get_or_create(
                                source=src_ci,
                                target=tgt_ci,
                                relation_type=_map_relation_type(rel_type),
                            )
                            if created:
                                stats['created'] += 1
                            else:
                                stats['skipped'] += 1

    return stats


def sync_tickets(ds):
    """同步 iTop 工单 → TransactionTicket"""
    ticket_classes = ds.config.get('ticket_classes', DEFAULT_TICKET_CLASSES) if ds.config else DEFAULT_TICKET_CLASSES
    stats = {'created': 0, 'updated': 0}

    for itop_class in ticket_classes:
        result = _call_itop_api(ds, '{"operation":"core/get","class":"%s","key":"SELECT %s","output_fields":"*"}' % (
            itop_class, itop_class
        ))
        if result.get('code') != 0:
            continue

        ticket_type = TICKET_TYPE_MAP.get(itop_class, TransactionTicket.TYPE_CHANGE)
        objects = (result.get('objects') or {})
        for _, obj in objects.items():
            if obj.get('code') != 0:
                continue
            fields = obj.get('fields', {})
            external_id = f'itop:{itop_class}:{obj.get("key")}'

            defaults = {
                'ticket_type': ticket_type,
                'title': fields.get('title') or fields.get('ref') or f'{itop_class}#{obj.get("key")}',
                'description': fields.get('description', ''),
                'priority': _map_itop_priority(fields.get('priority', 'medium')),
                'status': _map_ticket_status(fields.get('status', 'new')),
                'applicant': fields.get('caller_name', 'iTop Sync'),
                'external_source': 'itop',
                'external_id': external_id,
                'external_url': f'{ds.api_url.replace("/webservices/rest.php", "")}/?operation=details&class={itop_class}&id={obj.get("key")}',
            }

            existing = TransactionTicket.objects.filter(external_source='itop', external_id=external_id).first()
            if existing:
                for k, v in defaults.items():
                    if k not in ('external_source', 'external_id'):
                        setattr(existing, k, v)
                existing.save()
                stats['updated'] += 1
            else:
                TransactionTicket.objects.create(**defaults)
                stats['created'] += 1

    return stats


def run_full_sync(ds):
    """执行全量同步"""
    ds.sync_status = 'running'
    ds.save(update_fields=['sync_status'])
    try:
        ci_type_result = sync_ci_classes(ds)
        ci_result = sync_cis(ds)
        rel_result = sync_relations(ds)
        ticket_result = sync_tickets(ds)
        ds.last_sync_at = now()
        ds.sync_status = 'ok'

        # 触发设备映射对账
        try:
            from ops.device_matcher import reconcile_device_mappings
            stats = reconcile_device_mappings()
            if stats.get('repaired') or stats.get('created'):
                ds.sync_status = f'ok (设备映射: 修复{stats.get("repaired",0)} 新建{stats.get("created",0)})'
        except Exception as e:
            logging.getLogger(__name__).warning('reconcile_device_mappings failed after iTop sync: %s', e)

        return {
            'ci_types': ci_type_result,
            'cis': ci_result,
            'relations': rel_result,
            'tickets': ticket_result,
        }
    except Exception as e:
        ds.sync_status = f'error: {str(e)[:100]}'
        raise
    finally:
        ds.save(update_fields=['last_sync_at', 'sync_status'])


# ---- helper functions ----

def _parse_itop_key(itop_key):
    """解析 iTop key 'ClassName::id' → (class_name, obj_id)"""
    parts = (itop_key or '').split('::', 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return None, None


def _ensure_ci_class(itop_class, ds):
    """动态注册 iTop CI 类：在 class_map 中则返回已有 CIType，否则自动创建"""
    class_map = ds.config.get('ci_class_map', DEFAULT_CI_CLASS_MAP) if ds.config else dict(DEFAULT_CI_CLASS_MAP)
    if itop_class in class_map:
        ci_type_name = class_map[itop_class]
    else:
        ci_type_name = itop_class
        class_map[itop_class] = ci_type_name
        if ds.config is not None:
            ds.config['ci_class_map'] = class_map
            ds.save(update_fields=['config'])
    ci_type, _ = CIType.objects.get_or_create(
        name=ci_type_name,
        defaults={'description': f'从 iTop 自动发现的 {ci_type_name}'},
    )
    return ci_type


def _ensure_ci_from_itop(itop_key, ds):
    """确保 iTop 对象在本地有对应 ConfigItem（不存在则从 iTop 按需拉取）"""
    ci = _find_ci_by_itop_key(itop_key)
    if ci:
        return ci

    class_name, obj_id = _parse_itop_key(itop_key)
    if not class_name or not obj_id:
        return None

    ci_type = _ensure_ci_class(class_name, ds)

    result = _call_itop_api(ds, json.dumps({
        'operation': 'core/get',
        'class': class_name,
        'key': f'SELECT {class_name} WHERE id={obj_id}',
        'output_fields': '*',
    }))
    if result.get('code') != 0:
        return None

    objects = result.get('objects', {})
    for key, obj in objects.items():
        if obj.get('code') != 0:
            continue
        fields = obj.get('fields', {})
        obj_key = obj.get('key')
        if not obj_key:
            continue
        name = fields.get('name') or fields.get('friendlyname') or key
        external_id = f'itop:{class_name}:{obj_key}'

        bl = name if class_name == 'ApplicationSolution' else (fields.get('org_name', '') or ds.organization or '')

        ci, _ = ConfigItem.objects.update_or_create(
            external_id=external_id,
            defaults={
                'ci_type': ci_type,
                'business_line': bl,
                'environment': 'prod',
                'status': _map_itop_status(fields.get('status', '')),
                'itop_datasource': ds,
                'name': name,
                'attributes': {k: v for k, v in fields.items()
                               if k not in ('id', 'name', 'friendlyname', 'status', 'org_name')},
            },
        )
        try:
            from ops.device_matcher import match_ci_to_zabbix
            match_ci_to_zabbix(ci)
        except Exception as e:
            logging.getLogger(__name__).warning('match_ci_to_zabbix failed in _ensure_ci_from_itop for %s: %s', name, e)
        return ci

    return None


def _find_ci_by_itop_key(itop_key):
    """根据 iTop key 查找对应的 ConfigItem（优先 external_id 精确匹配）"""
    # 1. 直接匹配 external_id
    ci = ConfigItem.objects.filter(external_id=itop_key).first()
    if ci:
        return ci
    # 2. iTop key 格式 'ClassName::id' → 转成 external_id 格式 'itop:ClassName:id'
    if '::' in (itop_key or ''):
        ext_id = 'itop:' + itop_key.replace('::', ':', 1)
        ci = ConfigItem.objects.filter(external_id=ext_id).first()
        if ci:
            return ci
    # 3. 如果已经是 'itop:ClassName:id' 格式，尝试反向匹配
    if (itop_key or '').startswith('itop:'):
        ci = ConfigItem.objects.filter(external_id=itop_key).first()
        if ci:
            return ci
    return None


def _map_relation_type(rel_type):
    rel_map = {'impacts': 'depends_on', 'depends_on': 'depends_on'}
    return rel_map.get(rel_type, 'connects_to')


def _map_itop_status(status):
    status_map = {
        'production': 'active', 'implementation': 'active',
        'obsolete': 'offline', 'stock': 'idle',
    }
    return status_map.get(status.lower() if status else '', 'active')


def _map_itop_priority(priority):
    prio_map = {'1': 'high', '2': 'high', '3': 'medium', '4': 'low'}
    return prio_map.get(str(priority), 'medium')


def _map_ticket_status(status):
    status_map = {
        'new': TransactionTicket.STATUS_PENDING,
        'assigned': TransactionTicket.STATUS_PROCESSING,
        'resolved': TransactionTicket.STATUS_DONE,
        'closed': TransactionTicket.STATUS_DONE,
        'rejected': TransactionTicket.STATUS_REJECTED,
        'approved': TransactionTicket.STATUS_APPROVED,
    }
    return status_map.get(status.lower() if status else 'new', TransactionTicket.STATUS_PENDING)
