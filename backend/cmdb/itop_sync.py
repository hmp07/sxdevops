"""iTop 数据同步引擎 — 将 iTop CMDB/工单数据批量同步到本地模型."""
import json
import logging
import requests
from django.utils.timezone import now
from cmdb.models import CIType, ConfigItem, CIRelation, iTopDataSource, RelationType
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

# iTop 3.0.4 itop-config-mgmt 数据模型全部 lnk 关系类（盘点清单，映射完整性由测试锁死）
# 来源：Combodo/iTop tag 3.0.4 datamodels/2.x/itop-config-mgmt/datamodel.itop-config-mgmt.xml
ITOP_LNK_CLASSES = [
    'lnkApplicationSolutionToFunctionalCI',
    'lnkApplicationSolutionToBusinessProcess',
    'lnkConnectableCIToNetworkDevice',
    'lnkSubnetToVLAN',
    'lnkPhysicalInterfaceToVLAN',
    'lnkGroupToCI',
    'lnkContactToFunctionalCI',
    'lnkDocumentToFunctionalCI',
    'lnkDocumentToSoftware',
    'lnkDocumentToLicence',
    'lnkDocumentToPatch',
    'lnkSoftwareInstanceToSoftwarePatch',
    'lnkFunctionalCIToOSPatch',
]

# iTop 关系名 → 平台落点映射（V2.0 本体属性映射）
#   code: CIRelation 注册表关系码（RelationType.code）
#   direction: get_related 方向；'up' 表示返回上游，写 CIRelation 时交换 source/target
#   mode: relation=建 CIRelation；attributes=写 ConfigItem.attributes[attribute]；skip=不建模（最小本体）
# LinkedSet 关系（DBServer.dbschema_list 等）经 core/get 属性读取，暂不在 sync_relations 拉取路径，
#   映射见 ITOP_LINKSET_MAP（供后续扩展与文档对照）
ITOP_RELATION_MAP = {
    # 通用虚拟关系（core/get_related 聚合关系）
    'impacts': {'code': 'depends_on', 'direction': 'down', 'mode': 'relation'},
    'depends on': {'code': 'depends_on', 'direction': 'up', 'mode': 'relation'},
    # lnk 关系类
    'lnkApplicationSolutionToFunctionalCI': {'code': 'depends_on', 'direction': 'down', 'mode': 'relation'},
    'lnkApplicationSolutionToBusinessProcess': {'code': 'depends_on', 'direction': 'down', 'mode': 'relation'},
    'lnkConnectableCIToNetworkDevice': {'code': 'connects_to', 'direction': 'down', 'mode': 'relation'},
    'lnkSubnetToVLAN': {'code': 'connects_to', 'direction': 'down', 'mode': 'relation'},
    'lnkPhysicalInterfaceToVLAN': {'code': 'connects_to', 'direction': 'down', 'mode': 'relation'},
    'lnkGroupToCI': {'code': 'depends_on', 'direction': 'down', 'mode': 'attributes', 'attribute': 'owner_group'},
    'lnkContactToFunctionalCI': {'code': 'depends_on', 'direction': 'down', 'mode': 'attributes', 'attribute': 'owner_contact'},
    'lnkDocumentToFunctionalCI': {'code': 'depends_on', 'direction': 'down', 'mode': 'attributes', 'attribute': 'document_refs'},
    'lnkDocumentToSoftware': {'code': 'connects_to', 'direction': 'down', 'mode': 'skip'},
    'lnkDocumentToLicence': {'code': 'connects_to', 'direction': 'down', 'mode': 'skip'},
    'lnkDocumentToPatch': {'code': 'connects_to', 'direction': 'down', 'mode': 'skip'},
    'lnkSoftwareInstanceToSoftwarePatch': {'code': 'connects_to', 'direction': 'down', 'mode': 'skip'},
    'lnkFunctionalCIToOSPatch': {'code': 'connects_to', 'direction': 'down', 'mode': 'skip'},
}

# LinkedSet 链接集映射（n-n 属性实现，经 core/get 读取；本期仅落映射常量供文档对照）
ITOP_LINKSET_MAP = {
    'DBServer.dbschema_list': {'code': 'contains', 'direction': 'down', 'mode': 'relation'},
    'WebServer.webapp_list': {'code': 'depends_on', 'direction': 'down', 'mode': 'relation'},
    'Middleware.middlewareinstance_list': {'code': 'hosted_on', 'direction': 'down', 'mode': 'relation'},
    'VirtualizationSystem.virtualmachines_list': {'code': 'hosted_on', 'direction': 'down', 'mode': 'relation'},
    'ConnectableCI.physicalinterface_list': {'code': 'connects_to', 'direction': 'down', 'mode': 'attributes', 'attribute': 'interfaces'},
}


def _call_itop_api(ds, json_data, timeout=60):
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
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        return {'code': -1, 'message': str(e)}


def test_connection(ds, timeout=10):
    """测试 iTop 连接（保存门禁用 10s，留出网络余量保证前端 15s 内返回）"""
    result = _call_itop_api(ds, json.dumps({
        'operation': 'core/check_credentials',
        'user': ds.auth_user,
        'password': ds.auth_password,
    }), timeout=timeout)
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
    stats = {'created': 0, 'updated': 0, 'skipped': 0, 'errors': []}

    for itop_class in ci_classes:
        if itop_class not in class_map:
            continue
        result = _call_itop_api(ds, '{"operation":"core/get","class":"%s","key":"SELECT %s","output_fields":"*"}' % (
            itop_class, itop_class
        ))
        if result.get('code') != 0:
            stats['skipped'] += 1
            stats['errors'].append(f'{itop_class}: {result.get("message", "未知错误")}')
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
    """同步 CI 关系 → CIRelation（映射表驱动：ITOP_RELATION_MAP）。

    ds.config 支持：
      relation_types: str 列表（旧形态，兼容）或 {iTop关系名: {code, direction, mode, attribute}} dict
      relation_cleanup: True 时删除 iTop 已消失的本地关系（默认关）
    """
    class_map = ds.config.get('ci_class_map', DEFAULT_CI_CLASS_MAP) if ds.config else DEFAULT_CI_CLASS_MAP
    ci_classes = ds.config.get('ci_classes', list(class_map.keys())) if ds.config else list(class_map.keys())
    raw_relation_types = ds.config.get('relation_types', list(ITOP_RELATION_MAP.keys())) if ds.config else list(ITOP_RELATION_MAP.keys())
    stats = {'created': 0, 'skipped': 0, 'removed': 0, 'ignored_specs': 0}
    failed_calls = 0
    seen_relation_ids = []

    # 归一化：str 列表 → 按映射表展开为 spec dict
    relation_specs = {}
    if isinstance(raw_relation_types, dict):
        relation_specs = dict(raw_relation_types)
    else:
        for rel_name in raw_relation_types:
            relation_specs[rel_name] = dict(ITOP_RELATION_MAP.get(rel_name, {}))

    # 注册表校验：relation 模式下 code 必须存在于 RelationType，否则跳过（防 FK IntegrityError 中断整轮）
    valid_codes = set(RelationType.objects.values_list('code', flat=True))
    for rel_name, spec in list(relation_specs.items()):
        if spec.get('mode', 'relation') == 'relation':
            code = spec.get('code') or _map_relation_type(rel_name)
            if code not in valid_codes:
                logger_warning = logging.getLogger(__name__)
                logger_warning.warning('itop_sync: 忽略未注册的关系码 %s（%s）', code, rel_name)
                relation_specs.pop(rel_name, None)
                stats['ignored_specs'] += 1

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
            for rel_name, spec in relation_specs.items():
                mode = spec.get('mode', 'relation')
                if mode == 'skip':
                    continue
                direction = spec.get('direction', 'down')
                rel_result = _call_itop_api(ds,
                    '{"operation":"core/get_related","class":"%s","key":%s,"relation":"%s","depth":1,"direction":"%s"}' % (
                        itop_class, obj_id, rel_name, direction
                    ))
                if rel_result.get('code') != 0:
                    failed_calls += 1
                    continue
                relations = rel_result.get('relations') or {}
                if isinstance(relations, list):
                    # iTop returns relations as a flat list; treat source==obj, target from list
                    relations = {key: relations}
                for src_key, targets in relations.items():
                    src_ci = _ensure_ci_from_itop(src_key, ds)
                    if not src_ci:
                        continue
                    for target in (targets if isinstance(targets, list) else [targets]):
                        tgt_key = target.get('key', '')
                        tgt_ci = _ensure_ci_from_itop(tgt_key, ds)
                        if not tgt_ci:
                            continue
                        if mode == 'attributes':
                            # 数据属性模式：负责人/联系人/接口清单等，写入 ConfigItem.attributes（CI 名称，本地可用引用）
                            attribute = spec.get('attribute', 'related_refs')
                            ref_value = tgt_ci.name or tgt_key
                            refs = list(src_ci.attributes.get(attribute) or [])
                            if ref_value not in refs:
                                refs.append(ref_value)
                                src_ci.attributes[attribute] = refs
                                src_ci.save(update_fields=['attributes'])
                                stats['created'] += 1
                            else:
                                stats['skipped'] += 1
                            continue
                        code = spec.get('code') or _map_relation_type(rel_name)
                        # direction=up 表示 iTop 返回的是上游（被依赖方）→ 上游影响本对象，交换方向
                        if direction == 'up':
                            source_ci, target_ci = tgt_ci, src_ci
                        else:
                            source_ci, target_ci = src_ci, tgt_ci
                        rel, created = CIRelation.objects.get_or_create(
                            source=source_ci,
                            target=target_ci,
                            relation_type_id=code,
                        )
                        seen_relation_ids.append(rel.id)
                        if created:
                            stats['created'] += 1
                        else:
                            stats['skipped'] += 1

    # 清理 iTop 已消失的关系（默认关；仅影响两端均属本数据源的 CIRelation）
    # 失败门控：本轮任一 get_related 失败时跳过清理，防瞬态 iTop 故障导致全量误删
    if ds.config.get('relation_cleanup') and failed_calls == 0:
        stale_qs = CIRelation.objects.filter(
            source__itop_datasource=ds,
            target__itop_datasource=ds,
        ).exclude(id__in=seen_relation_ids)
        stats['removed'] = stale_qs.count()
        stale_qs.delete()

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
        if ci_result.get('errors') and not ci_result.get('created') and not ci_result.get('updated'):
            # 所有 CI 类请求全部失败（地址/凭据/网络问题），状态如实呈现，避免"已触发但无数据"误导
            ds.sync_status = 'error: 所有 CI 类同步失败（请检查数据源地址与凭据）'

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
