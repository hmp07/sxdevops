"""Zabbix 主机 ↔ iTop CI 设备关联匹配引擎."""


def extract_ip_from_zabbix_host(host: dict) -> str | None:
    """从 Zabbix host 对象提取主接口 IP"""
    interfaces = host.get('interfaces', []) or []
    main = next((i for i in interfaces if str(i.get('main', '')) == '1'), None)
    iface = main or (interfaces[0] if interfaces else None)
    if not iface:
        return None
    return (iface.get('ip') or '').strip() or None


def _extract_ci_ip(attrs: dict) -> str:
    """从 CI attributes 中提取 IP（兼容 iTop 多字段格式）"""
    if not attrs:
        return ''
    return (
        attrs.get('ip_address') or
        attrs.get('managementip') or
        attrs.get('managementip_id_friendlyname') or  # iTop 实际存储 IP 的字段
        ''
    ).strip()


def find_ci_by_ip(ip: str, prefer_itop: bool = True):
    """按 IP 在 ConfigItem 中查找匹配的 CI（JSONField 查询）

    prefer_itop=True 时优先返回 iTop 来源的 CI，找不到再返回任意 CI
    """
    if not ip:
        return None
    from cmdb.models import ConfigItem
    from django.db.models import Q
    q = (
        Q(attributes__ip_address=ip) |
        Q(attributes__managementip=ip) |
        Q(attributes__managementip_id_friendlyname=ip)
    )
    if prefer_itop:
        ci = ConfigItem.objects.filter(q, itop_datasource__isnull=False).select_related('ci_type').first()
        if ci:
            return ci
    return ConfigItem.objects.filter(q).select_related('ci_type').first()


def find_ci_by_name(name: str, prefer_itop: bool = True):
    """按名称在 ConfigItem 中查找匹配的 CI（含模糊匹配）

    prefer_itop=True 时优先返回 iTop 来源的 CI，找不到再返回任意 CI
    支持处理 "vm-mysql57" vs "mysql57" 类命名差异
    """
    if not name:
        return None
    from cmdb.models import ConfigItem
    name_clean = name.strip().lower()

    # 1. 精确匹配名称
    q = ConfigItem.objects.filter(name__iexact=name.strip())
    if prefer_itop:
        ci = q.filter(itop_datasource__isnull=False).first()
        if ci:
            return ci
    ci = q.first()
    if ci:
        return ci

    # 2. 模糊匹配：iTop CI 名包含 Zabbix 主机名 或 Zabbix 主机名包含 iTop CI 名
    for ci_obj in ConfigItem.objects.filter(itop_datasource__isnull=False).only('id', 'name'):
        ci_name = (ci_obj.name or '').strip().lower()
        if not ci_name or ci_name == name_clean:
            continue
        if name_clean in ci_name or ci_name in name_clean:
            return ConfigItem.objects.filter(id=ci_obj.id).select_related('ci_type').first()
    return None


def match_zabbix_host(host: dict):
    """为单个 Zabbix 主机查找并建立 CI 关联（优先匹配 iTop 权威 CI）"""
    from ops.models import DeviceMapping
    hostid = str(host.get('hostid', ''))
    hostname = host.get('name') or host.get('host', '')
    ip = extract_ip_from_zabbix_host(host)
    if not hostid:
        return None

    existing = DeviceMapping.objects.filter(zabbix_hostid=hostid).first()
    if existing:
        existing.zabbix_hostname = hostname
        existing.zabbix_ip = ip or existing.zabbix_ip
        existing.save(update_fields=['zabbix_hostname', 'zabbix_ip'])
        # 如果已有映射指向非 iTop CI，尝试升级为 iTop CI
        if existing.config_item_id and not getattr(existing.config_item, 'itop_datasource_id', None):
            if ip:
                itop_ci = find_ci_by_ip(ip, prefer_itop=True)
                if itop_ci and itop_ci.itop_datasource_id:
                    existing.config_item = itop_ci
                    existing.match_method = DeviceMapping.MATCH_IP
                    existing.match_confidence = 1.0
                    existing.save(update_fields=['config_item', 'match_method', 'match_confidence'])
        return existing

    mapping = DeviceMapping(
        zabbix_hostid=hostid,
        zabbix_hostname=hostname,
        zabbix_ip=ip or '',
    )
    matched = False
    # 优先匹配 iTop 来源的 CI
    if ip:
        ci = find_ci_by_ip(ip, prefer_itop=True)
        if ci:
            mapping.config_item = ci
            mapping.match_method = DeviceMapping.MATCH_IP
            mapping.match_confidence = 1.0
            matched = True
    if not matched:
        ci = find_ci_by_name(hostname, prefer_itop=True)
        if ci:
            mapping.config_item = ci
            mapping.match_method = DeviceMapping.MATCH_NAME
            mapping.match_confidence = 0.7
    mapping.save()
    return mapping


def match_all_zabbix_hosts(hosts: list) -> dict:
    """批量匹配 Zabbix 主机列表"""
    stats = {'matched': 0, 'unmatched': 0, 'total': len(hosts)}
    for host in hosts:
        m = match_zabbix_host(host)
        if m and m.config_item_id:
            stats['matched'] += 1
        else:
            stats['unmatched'] += 1
    return stats


def match_ci_to_zabbix(config_item):
    """iTop 同步后，为新 CI 查找匹配的 Zabbix 主机（IP 优先，名称降级）"""
    from ops.models import DeviceMapping
    ci_ip = _extract_ci_ip(config_item.attributes or {})

    existing = DeviceMapping.objects.filter(config_item=config_item).first()
    if existing:
        return existing

    # 主匹配：IP 精确匹配
    if ci_ip:
        mapping = DeviceMapping.objects.filter(zabbix_ip=ci_ip, config_item__isnull=True).first()
        if mapping:
            mapping.config_item = config_item
            mapping.match_method = DeviceMapping.MATCH_IP
            mapping.match_confidence = 1.0
            mapping.save(update_fields=['config_item', 'match_method', 'match_confidence'])
            return mapping

    # 降级匹配：CI 名称匹配 Zabbix 主机名
    ci_name = (config_item.name or '').strip()
    if ci_name:
        mapping = DeviceMapping.objects.filter(
            zabbix_hostname__iexact=ci_name, config_item__isnull=True
        ).first()
        if mapping:
            mapping.config_item = config_item
            mapping.match_method = DeviceMapping.MATCH_NAME
            mapping.match_confidence = 0.7
            mapping.save(update_fields=['config_item', 'match_method', 'match_confidence'])
            return mapping
    return None


def reconcile_device_mappings() -> dict:
    """统一对账：双向匹配 Zabbix 主机 ↔ iTop CI，跳过人工确认的映射

    在 iTop 同步完成和 Zabbix 主机导入完成时调用。
    多次运行幂等，不会创建重复映射。
    """
    from ops.models import DeviceMapping
    from cmdb.models import ConfigItem

    stats = {'repaired': 0, 'created': 0, 'skipped_verified': 0, 'unchanged': 0}

    # ---- 1. Zabbix → CI：修复断裂的映射 ----
    for mapping in DeviceMapping.objects.select_related('config_item'):
        if mapping.is_verified:
            stats['skipped_verified'] += 1
            continue

        ci = mapping.config_item
        need_repair = False

        if ci is None:
            # 映射断裂（旧 CI 被删除）
            need_repair = True
        else:
            # 检查现有 CI 的 IP 是否仍匹配
            ci_ip = _extract_ci_ip(ci.attributes or {})
            if not ci_ip or ci_ip != mapping.zabbix_ip:
                need_repair = True

        if need_repair:
            ci = None
            # 优先匹配 iTop 权威 CI
            if mapping.zabbix_ip:
                ci = find_ci_by_ip(mapping.zabbix_ip, prefer_itop=True)
            if not ci:
                ci = find_ci_by_name(mapping.zabbix_hostname, prefer_itop=True)
            if ci:
                mapping.config_item = ci
                mapping.match_method = DeviceMapping.MATCH_IP if (mapping.zabbix_ip and _extract_ci_ip(ci.attributes or {}) == mapping.zabbix_ip) else DeviceMapping.MATCH_NAME
                mapping.match_confidence = 1.0 if mapping.match_method == DeviceMapping.MATCH_IP else 0.7
                mapping.save(update_fields=['config_item', 'match_method', 'match_confidence'])
                stats['repaired'] += 1
            else:
                # 找不到新 CI（含 config_item 为 None 的情况），保留状态
                stats['unchanged'] += 1
        else:
            stats['unchanged'] += 1

    # ---- 2. CI → Zabbix：为有 IP 但无映射的 CI 创建关联 ----
    for ci in ConfigItem.objects.select_related('ci_type').all():
        ci_ip = _extract_ci_ip(ci.attributes or {})
        if not ci_ip:
            continue
        # 已有映射的跳过
        if DeviceMapping.objects.filter(config_item=ci).exists():
            continue
        # 查找同 IP 的未关联 DeviceMapping
        mapping = DeviceMapping.objects.filter(zabbix_ip=ci_ip, config_item__isnull=True).first()
        if mapping:
            mapping.config_item = ci
            mapping.match_method = DeviceMapping.MATCH_IP
            mapping.match_confidence = 1.0
            mapping.save(update_fields=['config_item', 'match_method', 'match_confidence'])
            stats['created'] += 1
        else:
            # 降级：名称匹配
            ci_name = (ci.name or '').strip()
            if ci_name:
                mapping = DeviceMapping.objects.filter(
                    zabbix_hostname__iexact=ci_name, config_item__isnull=True
                ).first()
                if mapping:
                    mapping.config_item = ci
                    mapping.match_method = DeviceMapping.MATCH_NAME
                    mapping.match_confidence = 0.7
                    mapping.save(update_fields=['config_item', 'match_method', 'match_confidence'])
                    stats['created'] += 1

    return stats


def validate_mapping_consistency() -> dict:
    """核对 DeviceMapping 两侧数据一致性，返回异常报告

    Returns:
        {
            'total': N,
            'itop_linked': N,          # 指向 iTop CI 的映射数
            'non_itop_linked': N,      # 指向非 iTop CI 的映射数
            'unlinked': N,             # 未关联 CI 的映射数
            'name_mismatches': [...],  # Zabbix 名 ≠ CI 名的映射
            'ip_mismatches': [...],    # Zabbix IP ≠ CI IP 的映射
            'orphan_itop_cis': N,      # 无 DeviceMapping 的 iTop CI 数
        }
    """
    from ops.models import DeviceMapping
    from cmdb.models import ConfigItem

    report = {
        'total': 0, 'itop_linked': 0, 'non_itop_linked': 0, 'unlinked': 0,
        'name_mismatches': [], 'ip_mismatches': [],
        'orphan_itop_cis': 0,
    }

    for dm in DeviceMapping.objects.select_related('config_item__ci_type'):
        report['total'] += 1
        ci = dm.config_item
        if not ci:
            report['unlinked'] += 1
            continue

        has_itop = bool(getattr(ci, 'itop_datasource_id', None))
        if has_itop:
            report['itop_linked'] += 1
        else:
            report['non_itop_linked'] += 1

        # 名称不一致检查
        if dm.zabbix_hostname.lower() != ci.name.lower():
            report['name_mismatches'].append({
                'zabbix_hostname': dm.zabbix_hostname,
                'ci_name': ci.name,
                'ci_type': ci.ci_type.name if ci.ci_type else '',
                'dm_id': dm.id,
            })

        # IP 不一致检查
        ci_ip = _extract_ci_ip(ci.attributes or {})
        if dm.zabbix_ip and ci_ip and dm.zabbix_ip != ci_ip:
            report['ip_mismatches'].append({
                'zabbix_ip': dm.zabbix_ip,
                'ci_ip': ci_ip,
                'hostname': dm.zabbix_hostname,
                'dm_id': dm.id,
            })

    # 孤立 iTop CI（有 IP 但无 DM）
    dm_ci_ids = set(DeviceMapping.objects.filter(config_item__isnull=False).values_list('config_item_id', flat=True))
    for ci in ConfigItem.objects.filter(itop_datasource__isnull=False):
        attrs = ci.attributes or {}
        if _extract_ci_ip(attrs) and ci.id not in dm_ci_ids:
            report['orphan_itop_cis'] += 1

    return report


def repair_business_line_from_itop() -> dict:
    """以 iTop 为准，修复 Host/TaskResource 的 business_line

    对每个有 DeviceMapping→iTop CI 的 Zabbix Host，
    如果 iTop CI 有 business_line 而 Host 没有或不一致，
    以 iTop 为准更新 Host 和关联的 TaskResource。
    """
    from ops.models import Host, TaskResource, DeviceMapping

    stats = {'checked': 0, 'repaired_hosts': 0, 'repaired_resources': 0}
    for dm in DeviceMapping.objects.filter(
        config_item__isnull=False,
        config_item__itop_datasource__isnull=False,
    ).select_related('config_item'):
        itop_bl = (dm.config_item.business_line or '').strip()
        if not itop_bl:
            continue

        # 修复 Host（优先 external_id，找不到按主机名查找）
        host = Host.objects.filter(external_id=f'zabbix:{dm.zabbix_hostid}').first()
        if not host:
            host = Host.objects.filter(hostname__iexact=dm.zabbix_hostname).first()
        if host:
            stats['checked'] += 1
            host_bl = (host.business_line or '').strip()
            if not host_bl or host_bl != itop_bl:
                host.business_line = itop_bl
                host.save(update_fields=['business_line'])
                stats['repaired_hosts'] += 1

            # 修复关联的 TaskResource
            for tr in TaskResource.objects.filter(host=host):
                tr_bl = (getattr(tr, 'business_line', '') or '').strip()
                if tr_bl != itop_bl:
                    tr.system_name = itop_bl  # system_name 字段
                    tr.save(update_fields=['system_name'])
                    stats['repaired_resources'] += 1

    return stats


def get_device_mapping_for_hosts(host_ids: list) -> dict:
    """批量获取 Zabbix 主机的 DeviceMapping（用于前端列展示）"""
    from ops.models import DeviceMapping
    mappings = DeviceMapping.objects.filter(
        zabbix_hostid__in=[str(h) for h in host_ids]
    ).select_related('config_item__ci_type')
    return {m.zabbix_hostid: _serialize_mapping(m) for m in mappings}


def _serialize_mapping(mapping) -> dict:
    return {
        'zabbix_hostid': mapping.zabbix_hostid,
        'zabbix_hostname': mapping.zabbix_hostname,
        'zabbix_ip': mapping.zabbix_ip,
        'match_method': mapping.match_method,
        'match_confidence': mapping.match_confidence,
        'is_verified': mapping.is_verified,
        'config_item': {
            'id': mapping.config_item.id,
            'name': mapping.config_item.name,
            'ci_type': mapping.config_item.ci_type.name if mapping.config_item.ci_type else '',
            'status': mapping.config_item.status,
            'business_line': mapping.config_item.business_line,
            'environment': mapping.config_item.environment,
        } if mapping.config_item else None,
    }
