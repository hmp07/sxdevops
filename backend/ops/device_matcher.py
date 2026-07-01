"""Zabbix 主机 ↔ iTop CI 设备关联匹配引擎."""


def extract_ip_from_zabbix_host(host: dict) -> str | None:
    """从 Zabbix host 对象提取主接口 IP"""
    interfaces = host.get('interfaces', []) or []
    main = next((i for i in interfaces if str(i.get('main', '')) == '1'), None)
    iface = main or (interfaces[0] if interfaces else None)
    if not iface:
        return None
    return (iface.get('ip') or '').strip() or None


def find_ci_by_ip(ip: str):
    """按 IP 在 ConfigItem 中查找匹配的 CI"""
    if not ip:
        return None
    from cmdb.models import ConfigItem
    for ci in ConfigItem.objects.select_related('ci_type').all():
        attrs = ci.attributes or {}
        ci_ip = (attrs.get('ip_address') or attrs.get('managementip') or '').strip()
        if ci_ip and ci_ip == ip:
            return ci
    return None


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
    if ip:
        ci = find_ci_by_ip(ip)
        if ci:
            mapping.config_item = ci
            mapping.match_method = DeviceMapping.MATCH_IP
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
    """iTop 同步后，为新 CI 查找匹配的 Zabbix 主机"""
    from ops.models import DeviceMapping
    attrs = config_item.attributes or {}
    ci_ip = (attrs.get('ip_address') or attrs.get('managementip') or '').strip()
    if not ci_ip:
        return None

    existing = DeviceMapping.objects.filter(config_item=config_item).first()
    if existing:
        return existing

    mapping = DeviceMapping.objects.filter(zabbix_ip=ci_ip, config_item__isnull=True).first()
    if mapping:
        mapping.config_item = config_item
        mapping.match_confidence = 1.0
        mapping.save(update_fields=['config_item', 'match_confidence'])
    return mapping


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
