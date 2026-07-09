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


def find_ci_by_ip(ip: str):
    """按 IP 在 ConfigItem 中查找匹配的 CI（JSONField 查询）"""
    if not ip:
        return None
    from cmdb.models import ConfigItem
    from django.db.models import Q
    return ConfigItem.objects.filter(
        Q(attributes__ip_address=ip) |
        Q(attributes__managementip=ip) |
        Q(attributes__managementip_id_friendlyname=ip)
    ).select_related('ci_type').first()


def find_ci_by_name(name: str):
    """按名称在 ConfigItem 中查找匹配的 CI（IP 匹配失败时的降级方案）"""
    if not name:
        return None
    from cmdb.models import ConfigItem
    return ConfigItem.objects.filter(name__iexact=name.strip()).first()


def match_zabbix_host(host: dict):
    """为单个 Zabbix 主机查找并建立 CI 关联"""
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
        return existing

    mapping = DeviceMapping(
        zabbix_hostid=hostid,
        zabbix_hostname=hostname,
        zabbix_ip=ip or '',
    )
    matched = False
    if ip:
        ci = find_ci_by_ip(ip)
        if ci:
            mapping.config_item = ci
            mapping.match_method = DeviceMapping.MATCH_IP
            mapping.match_confidence = 1.0
            matched = True
    if not matched:
        ci = find_ci_by_name(hostname)
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
            if mapping.zabbix_ip:
                ci = find_ci_by_ip(mapping.zabbix_ip)
            if not ci:
                ci = find_ci_by_name(mapping.zabbix_hostname)
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
