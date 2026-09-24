"""Oracle 域演示 CI 类型与演示域种子。

承接 iTop 标准模型缺失的存储域/数据库组件类（V2.0 本体方案 §3）：
    存储系统(layer 0) → 存储卷(layer 0)
    Oracle监听/Oracle实例(layer 2) → 表空间(layer 3) → 数据文件/归档日志(layer 4)

与 cmdb/demo_seed.py 保持幂等种子风格；实例链与依赖关系见 seed_oracle_domain()。
"""

from .models import CIType

ORACLE_CI_TYPES = [
    {'name': '存储系统', 'color': '#e67e22', 'icon': 'Coin', 'layer': 0,
     'description': '存储阵列/SAN 系统（V2.0 本体 StorageResource 落点）'},
    {'name': '存储卷', 'color': '#d35400', 'icon': 'Coin', 'layer': 0,
     'description': '存储 LUN/卷（V2.0 StorageVolume）'},
    {'name': 'Oracle监听', 'color': '#16a085', 'icon': 'Headset', 'layer': 2,
     'description': 'Oracle 监听进程（V2.0 OracleListener）'},
    {'name': 'Oracle实例', 'color': '#c0392b', 'icon': 'Coin', 'layer': 2,
     'description': 'Oracle 数据库实例（V2.0 OracleInstance）'},
    {'name': '表空间', 'color': '#2980b9', 'icon': 'FolderOpened', 'layer': 3,
     'description': 'Oracle 表空间（V2.0 Tablespace）'},
    {'name': '数据文件', 'color': '#8e44ad', 'icon': 'Document', 'layer': 4,
     'description': 'Oracle 数据文件（V2.0 Datafile）'},
    {'name': '归档日志', 'color': '#7f8c8d', 'icon': 'Document', 'layer': 4,
     'description': 'Oracle 归档日志（V2.0 ArchiveLog）'},
]


def seed_oracle_ci_types(stdout=None):
    """幂等创建 Oracle 域自定义 CI 类型。"""
    created = []
    for entry in ORACLE_CI_TYPES:
        _, is_new = CIType.objects.get_or_create(
            name=entry['name'],
            defaults={
                'color': entry['color'],
                'icon': entry['icon'],
                'layer': entry['layer'],
                'description': entry['description'],
            },
        )
        if is_new:
            created.append(entry['name'])
    if stdout is not None and created:
        stdout.write(f"Oracle 域 CI 类型：新增 {', '.join(created)}")
    return created


def seed_oracle_domain(stdout=None, business_line='交易平台', environment='prod'):
    """幂等创建 Oracle 域演示实例链与依赖关系（对应 V2.0 用例 04/05）。

    实例链：orcl-db-01(云主机) ← ORCL01(实例) ← TS_ORDER(表空间) ← ts_order_01.dbf(数据文件) ← lun-orders-01(存储卷) ← san-orders(存储系统)
    + listener-01(监听) + arch-01(归档存储卷)
    """
    from .models import CIRelation, ConfigItem

    seed_oracle_ci_types(stdout)

    host_type, _ = CIType.objects.get_or_create(
        name='云主机(ECS)', defaults={'icon': 'Monitor', 'color': '#3f51b5'})
    type_names = {entry['name'] for entry in ORACLE_CI_TYPES}
    types = {t.name: t for t in CIType.objects.filter(name__in=type_names)}
    types['云主机(ECS)'] = host_type

    def ensure_ci(ci_type_name, name, attributes=None):
        ci, _ = ConfigItem.objects.get_or_create(
            name=name,
            defaults={
                'ci_type': types[ci_type_name],
                'business_line': business_line,
                'environment': environment,
                'status': 'active',
                'attributes': attributes or {},
            },
        )
        return ci

    orcl_host = ensure_ci('云主机(ECS)', 'orcl-db-01', {'ip_address': '10.40.1.10'})
    orcl = ensure_ci('Oracle实例', 'ORCL01', {'instance_name': 'ORCL', 'oracle_version': '11g'})
    ts = ensure_ci('表空间', 'TS_ORDER', {'tablespace_used_pct': 99.5})
    df = ensure_ci('数据文件', 'ts_order_01.dbf')
    lun = ensure_ci('存储卷', 'lun-orders-01', {'volume_util_pct': 85})
    san = ensure_ci('存储系统', 'san-orders')
    listener = ensure_ci('Oracle监听', 'listener-01', {'listener_port': 1521})
    arch = ensure_ci('存储卷', 'arch-01')

    relations = [
        (orcl, ts, 'contains', '实例包含表空间'),
        (ts, df, 'contains', '表空间包含数据文件'),
        (df, lun, 'depends_on', '数据文件存储于卷'),
        (lun, san, 'hosted_on', '存储卷承载于存储系统'),
        (orcl, orcl_host, 'hosted_on', '实例运行于主机'),
        (listener, orcl_host, 'hosted_on', '监听运行于主机'),
        (arch, san, 'hosted_on', '归档存储卷承载于存储系统'),
    ]
    created = 0
    for source, target, rel_code, desc in relations:
        _, is_new = CIRelation.objects.get_or_create(
            source=source, target=target, relation_type_id=rel_code,
            defaults={'description': desc},
        )
        if is_new:
            created += 1
    if stdout is not None:
        stdout.write(f'Oracle 域演示：8 个 CI，关系新增 {created} 条。')
    return {'cis': 8, 'relations_created': created}
