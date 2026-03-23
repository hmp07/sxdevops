"""
数据库执行器
支持 MySQL、PolarDB 与 MongoDB。
"""
import json
import time

import pymysql
from pymysql.cursors import DictCursor

try:
    from pymongo import MongoClient
except ImportError:  # pragma: no cover
    MongoClient = None


MYSQL_LIKE_TYPES = {'mysql', 'polardb'}
MONGODB_TYPE = 'mongodb'
MYSQL_SYSTEM_DATABASES = {'information_schema', 'mysql', 'performance_schema', 'sys'}
MONGODB_SYSTEM_DATABASES = {'admin', 'config', 'local'}
MONGODB_READ_ACTIONS = {'find', 'aggregate', 'count', 'distinct'}
MONGODB_WRITE_ACTIONS = {
    'insertone', 'insertmany',
    'updateone', 'updatemany',
    'deleteone', 'deletemany',
    'createcollection', 'dropcollection',
    'createindex', 'dropindex',
}


def _get_db_type(datasource):
    return getattr(datasource, 'db_type', 'mysql') or 'mysql'


def validate_query_content(datasource, sql_content):
    db_type = _get_db_type(datasource)
    if db_type == MONGODB_TYPE:
        try:
            action, _ = _parse_mongodb_command(sql_content)
        except ValueError as exc:
            return str(exc)
        if action not in MONGODB_READ_ACTIONS:
            return 'MongoDB 查询仅允许 find / aggregate / count / distinct 命令'
        return None

    upper = sql_content.strip().upper()
    if not upper.startswith('SELECT') and not upper.startswith('SHOW') and not upper.startswith('DESC'):
        return '查询工单只允许 SELECT / SHOW / DESC 语句'
    return None


def test_connection(datasource):
    db_type = _get_db_type(datasource)
    if db_type in MYSQL_LIKE_TYPES:
        return _test_mysql_connection(datasource)
    if db_type == MONGODB_TYPE:
        return _test_mongodb_connection(datasource)
    return False, f'暂不支持的数据源类型: {db_type}'


def get_databases(datasource):
    db_type = _get_db_type(datasource)
    if db_type in MYSQL_LIKE_TYPES:
        return _get_mysql_databases(datasource)
    if db_type == MONGODB_TYPE:
        return _get_mongodb_databases(datasource)
    return []


def execute_sql(datasource, database, sql_content):
    db_type = _get_db_type(datasource)
    if db_type in MYSQL_LIKE_TYPES:
        return _execute_mysql_sql(datasource, database, sql_content)
    if db_type == MONGODB_TYPE:
        return _execute_mongodb_write(datasource, database, sql_content)
    return False, 0, 0, f'暂不支持的数据源类型: {db_type}'


def execute_query(datasource, database, sql_content, limit=200):
    db_type = _get_db_type(datasource)
    if db_type in MYSQL_LIKE_TYPES:
        return _execute_mysql_query(datasource, database, sql_content, limit)
    if db_type == MONGODB_TYPE:
        return _execute_mongodb_query(datasource, database, sql_content, limit)
    return False, [], [], 0, 0, f'暂不支持的数据源类型: {db_type}'


def _build_mysql_connect_kwargs(datasource, database=None, cursorclass=None, autocommit=None, timeout=5):
    kwargs = {
        'host': datasource.host,
        'port': datasource.port,
        'user': datasource.user,
        'password': datasource.password,
        'charset': datasource.charset,
        'connect_timeout': timeout,
    }
    if database:
        kwargs['database'] = database
    if cursorclass:
        kwargs['cursorclass'] = cursorclass
    if autocommit is not None:
        kwargs['autocommit'] = autocommit
    return kwargs


def _test_mysql_connection(datasource):
    try:
        conn = pymysql.connect(**_build_mysql_connect_kwargs(datasource, timeout=5))
        conn.close()
        return True, '连接成功'
    except pymysql.Error as exc:
        return False, f'连接失败: {exc}'
    except Exception as exc:
        return False, f'连接异常: {exc}'


def _get_mysql_databases(datasource):
    try:
        conn = pymysql.connect(**_build_mysql_connect_kwargs(datasource, timeout=5))
        with conn.cursor() as cursor:
            cursor.execute('SHOW DATABASES')
            databases = [row[0] for row in cursor.fetchall()]
        conn.close()
        return [db for db in databases if db not in MYSQL_SYSTEM_DATABASES]
    except Exception:
        return []


def _execute_mysql_sql(datasource, database, sql_content):
    start = time.time()
    try:
        conn = pymysql.connect(**_build_mysql_connect_kwargs(datasource, database=database, autocommit=False, timeout=10))
        total_affected = 0
        logs = []
        try:
            with conn.cursor() as cursor:
                statements = [statement.strip() for statement in sql_content.split(';') if statement.strip()]
                for index, statement in enumerate(statements, 1):
                    cursor.execute(statement)
                    affected = cursor.rowcount
                    total_affected += max(affected, 0)
                    logs.append(f'语句 #{index}: 影响 {affected} 行')
            conn.commit()
            duration = int((time.time() - start) * 1000)
            return True, total_affected, duration, '\n'.join(logs)
        except Exception as exc:
            conn.rollback()
            duration = int((time.time() - start) * 1000)
            return False, 0, duration, f'执行失败: {exc}'
        finally:
            conn.close()
    except pymysql.Error as exc:
        duration = int((time.time() - start) * 1000)
        return False, 0, duration, f'连接失败: {exc}'
    except Exception as exc:
        duration = int((time.time() - start) * 1000)
        return False, 0, duration, f'执行异常: {exc}'


def _execute_mysql_query(datasource, database, sql_content, limit):
    start = time.time()
    try:
        conn = pymysql.connect(
            **_build_mysql_connect_kwargs(
                datasource,
                database=database,
                cursorclass=DictCursor,
                timeout=10,
            ),
        )
        with conn.cursor() as cursor:
            cursor.execute(sql_content)
            rows = cursor.fetchmany(limit)
            count = cursor.rowcount
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
        conn.close()
        duration = int((time.time() - start) * 1000)
        return True, columns, rows, count, duration, None
    except Exception as exc:
        duration = int((time.time() - start) * 1000)
        return False, [], [], 0, duration, str(exc)


def _ensure_pymongo():
    if MongoClient is None:
        raise RuntimeError('未安装 pymongo，无法连接 MongoDB 数据源')


def _get_mongo_client(datasource):
    _ensure_pymongo()
    kwargs = {
        'host': datasource.host,
        'port': datasource.port,
        'serverSelectionTimeoutMS': 5000,
    }
    if datasource.user:
        kwargs['username'] = datasource.user
    if datasource.password:
        kwargs['password'] = datasource.password
        kwargs['authSource'] = 'admin'
    return MongoClient(**kwargs)


def _test_mongodb_connection(datasource):
    try:
        client = _get_mongo_client(datasource)
        client.admin.command('ping')
        client.close()
        return True, '连接成功'
    except Exception as exc:
        return False, f'连接失败: {exc}'


def _get_mongodb_databases(datasource):
    try:
        client = _get_mongo_client(datasource)
        databases = [name for name in client.list_database_names() if name not in MONGODB_SYSTEM_DATABASES]
        client.close()
        return databases
    except Exception:
        return []


def _parse_mongodb_command(sql_content):
    command = (sql_content or '').strip()
    if not command:
        raise ValueError('MongoDB 命令不能为空')
    action, separator, payload = command.partition(' ')
    if not separator or not payload.strip():
        raise ValueError('MongoDB 命令格式应为：动作 + JSON 参数')
    try:
        return action.strip().lower(), json.loads(payload.strip())
    except json.JSONDecodeError as exc:
        raise ValueError(f'MongoDB 命令 JSON 解析失败: {exc}') from exc


def _normalize_mongo_value(value):
    if isinstance(value, dict):
        return {key: _normalize_mongo_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_mongo_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def _extract_columns(rows):
    columns = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                columns.append(key)
    return columns


def _execute_mongodb_query(datasource, database, sql_content, limit):
    start = time.time()
    client = None
    try:
        action, payload = _parse_mongodb_command(sql_content)
        if action not in MONGODB_READ_ACTIONS:
            return False, [], [], 0, 0, 'MongoDB 查询仅允许 find / aggregate / count / distinct 命令'

        client = _get_mongo_client(datasource)
        db = client[database]

        if action == 'find':
            collection = db[payload['collection']]
            cursor = collection.find(
                payload.get('filter', {}),
                payload.get('projection'),
            )
            sort = payload.get('sort')
            if sort:
                cursor = cursor.sort(list(sort.items()))
            skip = payload.get('skip')
            if skip:
                cursor = cursor.skip(int(skip))
            cursor = cursor.limit(int(payload.get('limit', limit)))
            rows = [_normalize_mongo_value(item) for item in cursor]
        elif action == 'aggregate':
            collection = db[payload['collection']]
            pipeline = payload.get('pipeline', [])
            rows = [_normalize_mongo_value(item) for item in collection.aggregate(pipeline)]
            rows = rows[:int(payload.get('limit', limit))]
        elif action == 'count':
            collection = db[payload['collection']]
            rows = [{'count': collection.count_documents(payload.get('filter', {}))}]
        else:
            collection = db[payload['collection']]
            rows = [{'value': _normalize_mongo_value(item)} for item in collection.distinct(payload['field'], payload.get('filter', {}))]
            rows = rows[:int(payload.get('limit', limit))]

        columns = _extract_columns(rows)
        duration = int((time.time() - start) * 1000)
        return True, columns, rows, len(rows), duration, None
    except Exception as exc:
        duration = int((time.time() - start) * 1000)
        return False, [], [], 0, duration, str(exc)
    finally:
        if client is not None:
            client.close()


def _execute_mongodb_write(datasource, database, sql_content):
    start = time.time()
    client = None
    try:
        action, payload = _parse_mongodb_command(sql_content)
        if action not in MONGODB_WRITE_ACTIONS:
            return False, 0, 0, 'MongoDB 变更仅支持 insert/update/delete/collection/index 相关命令'

        client = _get_mongo_client(datasource)
        db = client[database]
        affected_rows = 0

        if action == 'insertone':
            result = db[payload['collection']].insert_one(payload['document'])
            affected_rows = 1
            log = f'insertOne 成功，_id={result.inserted_id}'
        elif action == 'insertmany':
            result = db[payload['collection']].insert_many(payload.get('documents', []))
            affected_rows = len(result.inserted_ids)
            log = f'insertMany 成功，插入 {affected_rows} 条'
        elif action == 'updateone':
            result = db[payload['collection']].update_one(payload.get('filter', {}), payload['update'], upsert=payload.get('upsert', False))
            affected_rows = result.modified_count
            log = f'updateOne 完成，匹配 {result.matched_count} 条，修改 {result.modified_count} 条'
        elif action == 'updatemany':
            result = db[payload['collection']].update_many(payload.get('filter', {}), payload['update'], upsert=payload.get('upsert', False))
            affected_rows = result.modified_count
            log = f'updateMany 完成，匹配 {result.matched_count} 条，修改 {result.modified_count} 条'
        elif action == 'deleteone':
            result = db[payload['collection']].delete_one(payload.get('filter', {}))
            affected_rows = result.deleted_count
            log = f'deleteOne 完成，删除 {result.deleted_count} 条'
        elif action == 'deletemany':
            result = db[payload['collection']].delete_many(payload.get('filter', {}))
            affected_rows = result.deleted_count
            log = f'deleteMany 完成，删除 {result.deleted_count} 条'
        elif action == 'createcollection':
            db.create_collection(payload['name'])
            log = f'createCollection 完成，集合 {payload["name"]} 已创建'
        elif action == 'dropcollection':
            db.drop_collection(payload['name'])
            log = f'dropCollection 完成，集合 {payload["name"]} 已删除'
        elif action == 'createindex':
            index_name = db[payload['collection']].create_index(list(payload['keys'].items()), **payload.get('options', {}))
            log = f'createIndex 完成，索引名 {index_name}'
        else:
            db[payload['collection']].drop_index(payload['name'])
            log = f'dropIndex 完成，索引 {payload["name"]} 已删除'

        duration = int((time.time() - start) * 1000)
        return True, affected_rows, duration, log
    except Exception as exc:
        duration = int((time.time() - start) * 1000)
        return False, 0, duration, f'执行失败: {exc}'
    finally:
        if client is not None:
            client.close()
