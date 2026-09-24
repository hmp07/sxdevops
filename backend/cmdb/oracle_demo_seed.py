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
