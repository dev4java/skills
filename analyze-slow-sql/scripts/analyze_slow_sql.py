#!/usr/bin/env python3
"""
MySQL 慢查询日志分析脚本
用法: python3 analyze_slow_sql.py <slow_log_file>
"""
import re
import sys
from collections import defaultdict

# 预编译解析正则，避免在循环中重复编译
_RE_TIME = re.compile(r'# Time: (\S+)')
_RE_USER = re.compile(r'# User@Host: (\S+)\[.*?\] @\s+\[([^\]]*)\]')
_RE_SCHEMA = re.compile(r'# Schema: (\S*)')
_RE_STATS = re.compile(
    r'# Query_time: ([\d.]+)\s+Lock_time: ([\d.]+)\s+Rows_sent: (\d+)\s+Rows_examined: (\d+)'
)

# 预编译 normalize 正则
_RE_COMMENT = re.compile(r'/\*.*?\*/', re.DOTALL)
_RE_NUM = re.compile(r'\b\d+\b')
_RE_STR = re.compile(r"'[^']*'")
_RE_IN = re.compile(r'IN\s*\([\?,\s]+\)', re.IGNORECASE)
_RE_WS = re.compile(r'\s+')

# 预编译反模式检测正则
_RE_SELECT_STAR = re.compile(r'SELECT\s+\*', re.IGNORECASE)
_RE_WILDCARD_LIKE = re.compile(r"LIKE\s+'%[^']", re.IGNORECASE)
_RE_IN_SUBQUERY = re.compile(r'\bIN\s*\(\s*SELECT\b', re.IGNORECASE)
_RE_OR_COND = re.compile(r'\bOR\b', re.IGNORECASE)
_RE_ORDER_BY = re.compile(r'\bORDER\s+BY\b', re.IGNORECASE)
_RE_GROUP_BY = re.compile(r'\bGROUP\s+BY\b', re.IGNORECASE)
_RE_HAS_JOIN = re.compile(r'\b(?:LEFT|RIGHT|INNER|CROSS|FULL)?\s*JOIN\b', re.IGNORECASE)
_RE_HAS_LIMIT = re.compile(r'\bLIMIT\b', re.IGNORECASE)
_RE_IS_SELECT = re.compile(r'^\s*SELECT\b', re.IGNORECASE)
_RE_FUNC_ON_COL = re.compile(
    r'\b(?:DATE|DATE_FORMAT|YEAR|MONTH|DAY|SUBSTRING|UPPER|LOWER|TRIM|CAST|CONVERT)\s*\(',
    re.IGNORECASE,
)

# 提取 SQL 中涉及的表名
_RE_TABLE_REF = re.compile(
    r'\b(?:FROM|JOIN|UPDATE|INTO|TABLE)\s+`?([a-zA-Z_]\w*)`?', re.IGNORECASE
)
_SQL_KEYWORDS = frozenset(
    {
        'select',
        'where',
        'and',
        'or',
        'not',
        'in',
        'on',
        'set',
        'values',
        'dual',
        'null',
        'true',
        'false',
        'case',
        'when',
        'then',
        'else',
        'end',
        'as',
        'by',
        'asc',
        'desc',
        'limit',
        'offset',
        'having',
        'group',
        'order',
    }
)


def normalize(sql: str) -> str:
    """将 SQL 归一化为模式 key，移除字面量和注释，保留结构。"""
    s = sql.strip().upper()
    s = _RE_COMMENT.sub('', s)
    s = _RE_NUM.sub('?', s)
    s = _RE_STR.sub('?', s)
    s = _RE_IN.sub('IN (?)', s)
    return _RE_WS.sub(' ', s).strip()


def extract_tables(sql_list: list[str]) -> list[str]:
    """从 SQL 列表中提取所有涉及的表名，过滤 SQL 关键字。"""
    tables: set[str] = set()
    for sql in sql_list:
        for m in _RE_TABLE_REF.finditer(sql):
            name = m.group(1).lower()
            if name not in _SQL_KEYWORDS:
                tables.add(name)
    return sorted(tables)


def detect_antipatterns(sql: str) -> list[str]:
    """检测 SQL 反模式，返回标记列表。"""
    flags: list[str] = []
    if _RE_SELECT_STAR.search(sql):
        flags.append('SELECT_STAR')
    if _RE_WILDCARD_LIKE.search(sql):
        flags.append('WILDCARD_LIKE')
    if _RE_IN_SUBQUERY.search(sql):
        flags.append('IN_SUBQUERY')
    if _RE_OR_COND.search(sql):
        flags.append('HAS_OR')
    if _RE_ORDER_BY.search(sql):
        flags.append('ORDER_BY')
    if _RE_GROUP_BY.search(sql):
        flags.append('GROUP_BY')
    if _RE_HAS_JOIN.search(sql):
        flags.append('HAS_JOIN')
    if _RE_FUNC_ON_COL.search(sql):
        flags.append('FUNC_ON_COL')
    if _RE_IS_SELECT.match(sql) and not _RE_HAS_LIMIT.search(sql):
        flags.append('NO_LIMIT')
    return flags


def parse_log(log_file: str) -> list[dict]:
    queries: list[dict] = []
    current: dict = {}

    try:
        f = open(log_file, 'r', errors='replace')
    except FileNotFoundError:
        print(f"ERROR: 文件不存在: {log_file}", file=sys.stderr)
        sys.exit(1)

    with f:
        for line in f:
            line = line.rstrip()

            m = _RE_TIME.match(line)
            if m:
                if current.get('sql'):
                    queries.append(current)
                current = {'time': m.group(1)}
                continue

            m = _RE_USER.match(line)
            if m:
                current['user'] = m.group(1)
                current['host'] = m.group(2)
                continue

            m = _RE_SCHEMA.match(line)
            if m:
                current['schema'] = m.group(1) if m.group(1) else '(none)'
                continue

            m = _RE_STATS.match(line)
            if m:
                current['query_time'] = float(m.group(1))
                current['lock_time'] = float(m.group(2))
                current['rows_sent'] = int(m.group(3))
                current['rows_examined'] = int(m.group(4))
                continue

            # 跳过 MySQL 元数据行和 session 变量设置
            if (
                line.startswith('#')
                or line.startswith('SET timestamp')
                or line.startswith('SET @@')
                or line.startswith('use ')
            ):
                continue

            if line.strip() and not current.get('sql'):
                current['sql'] = line.strip()

    if current.get('sql'):
        queries.append(current)

    return queries


def build_pattern_stats(queries: list[dict]) -> dict:
    stats: dict = defaultdict(
        lambda: {
            'count': 0,
            'total_time': 0.0,
            'max_time': 0.0,
            'total_rows_examined': 0,
            'max_rows_examined': 0,
            'total_rows_sent': 0,
            'total_lock_time': 0.0,
            'max_lock_time': 0.0,
            'flags': [],
            'example': '',
            'schema': '',
            'user': '',
        }
    )
    for q in queries:
        # key 使用完整归一化 SQL，不截断，避免不同 pattern 被合并
        key = normalize(q.get('sql', ''))
        s = stats[key]
        s['count'] += 1
        s['total_time'] += q.get('query_time', 0)
        s['max_time'] = max(s['max_time'], q.get('query_time', 0))
        s['total_rows_examined'] += q.get('rows_examined', 0)
        s['max_rows_examined'] = max(s['max_rows_examined'], q.get('rows_examined', 0))
        s['total_rows_sent'] += q.get('rows_sent', 0)
        s['total_lock_time'] += q.get('lock_time', 0)
        s['max_lock_time'] = max(s['max_lock_time'], q.get('lock_time', 0))
        if not s['example']:
            s['example'] = q.get('sql', '').replace('\n', ' ')[:250]
            s['schema'] = q.get('schema', '')
            s['user'] = q.get('user', '')
            s['flags'] = detect_antipatterns(q.get('sql', ''))
    return stats


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python3 analyze_slow_sql.py <slow_log_file>", file=sys.stderr)
        sys.exit(1)

    queries = parse_log(sys.argv[1])
    total = len(queries)

    if total == 0:
        print("未找到慢查询记录，请确认文件格式是否为 MySQL slow query log。")
        sys.exit(0)

    times = [q.get('query_time', 0) for q in queries]
    all_times_str = [q['time'] for q in queries if q.get('time')]

    print("=== SUMMARY ===")
    print(f"total={total}")
    print(f"total_time={sum(times):.1f}")
    print(f"avg_time={sum(times)/total:.3f}")
    print(f"max_time={max(times):.3f}")
    print(f"min_time={min(times):.3f}")
    print(f"first_time={min(all_times_str) if all_times_str else 'unknown'}")
    print(f"last_time={max(all_times_str) if all_times_str else 'unknown'}")

    t1 = sum(1 for t in times if t < 2)
    t2 = sum(1 for t in times if 2 <= t < 5)
    t3 = sum(1 for t in times if 5 <= t < 10)
    t4 = sum(1 for t in times if 10 <= t < 30)
    t5 = sum(1 for t in times if t >= 30)
    print("=== DISTRIBUTION ===")
    print(f"1-2s={t1}|2-5s={t2}|5-10s={t3}|10-30s={t4}|>=30s={t5}")

    print("=== USERS ===")
    user_cnt: dict = defaultdict(int)
    user_time: dict = defaultdict(float)
    user_max: dict = defaultdict(float)
    for q in queries:
        u = q.get('user', 'unknown')
        user_cnt[u] += 1
        user_time[u] += q.get('query_time', 0)
        user_max[u] = max(user_max[u], q.get('query_time', 0))
    for u, cnt in sorted(user_cnt.items(), key=lambda x: -x[1]):
        print(f"{u}|{cnt}|{user_time[u]:.1f}|{user_max[u]:.2f}")

    print("=== SCHEMAS ===")
    sc_cnt: dict = defaultdict(int)
    sc_time: dict = defaultdict(float)
    for q in queries:
        s = q.get('schema', '(none)')
        sc_cnt[s] += 1
        sc_time[s] += q.get('query_time', 0)
    for s, cnt in sorted(sc_cnt.items(), key=lambda x: -x[1]):
        print(f"{s}|{cnt}|{sc_time[s]:.1f}")

    pattern_stats = build_pattern_stats(queries)

    print("=== TOP_TIME ===")
    for _, s in sorted(pattern_stats.items(), key=lambda x: -x[1]['total_time'])[:25]:
        avg = s['total_time'] / s['count']
        avg_rows = s['total_rows_examined'] // s['count']
        print(
            f"{s['total_time']:.1f}|{s['count']}|{avg:.2f}|{s['max_time']:.2f}"
            f"|{s['schema']}|{s['user']}|{s['max_rows_examined']}|{avg_rows}"
            f"|{s['max_lock_time']:.4f}|{s['total_lock_time']:.4f}|{s['example']}"
        )

    print("=== TOP_FREQ ===")
    for _, s in sorted(pattern_stats.items(), key=lambda x: -x[1]['count'])[:25]:
        avg = s['total_time'] / s['count']
        print(
            f"{s['count']}|{s['total_time']:.1f}|{avg:.2f}|{s['max_time']:.2f}"
            f"|{s['schema']}|{s['user']}|{s['max_rows_examined']}|{s['example']}"
        )

    print("=== TOP_SCAN ===")
    for _, s in sorted(pattern_stats.items(), key=lambda x: -x[1]['max_rows_examined'])[:20]:
        avg = s['total_time'] / s['count']
        print(
            f"{s['max_rows_examined']}|{s['count']}|{s['max_time']:.2f}|{avg:.2f}"
            f"|{s['schema']}|{s['user']}|{s['example']}"
        )

    print("=== DAILY ===")
    daily: dict = defaultdict(lambda: {'count': 0, 'total_time': 0.0})
    for q in queries:
        t = q.get('time', '')
        day = t[:10] if len(t) >= 10 else 'unknown'
        daily[day]['count'] += 1
        daily[day]['total_time'] += q.get('query_time', 0)
    for d in sorted(daily.keys())[-30:]:
        print(f"{d}|{daily[d]['count']}|{daily[d]['total_time']:.1f}")

    # 每个 SQL 模式的诊断信号，供 Claude 生成具体优化建议
    # 字段: total_time|count|avg_time|max_time|avg_rows_examined|max_rows_examined|
    #        efficiency_ratio|lock_ratio|flags|schema|user|example
    # efficiency_ratio = avg_rows_examined / max(avg_rows_sent, 1)，越大越说明扫描浪费越多
    # lock_ratio       = total_lock_time / total_time，越大越说明锁竞争严重
    print("=== SUGGESTIONS ===")
    for _, s in sorted(pattern_stats.items(), key=lambda x: -x[1]['total_time'])[:25]:
        avg_time = s['total_time'] / s['count']
        avg_examined = s['total_rows_examined'] // s['count']
        avg_sent = s['total_rows_sent'] // s['count']
        efficiency_ratio = avg_examined / max(avg_sent, 1)
        lock_ratio = s['total_lock_time'] / s['total_time'] if s['total_time'] > 0 else 0
        flags_str = ','.join(s['flags']) if s['flags'] else 'NONE'
        print(
            f"{s['total_time']:.1f}|{s['count']}|{avg_time:.2f}|{s['max_time']:.2f}"
            f"|{avg_examined}|{s['max_rows_examined']}"
            f"|{efficiency_ratio:.0f}|{lock_ratio:.3f}"
            f"|{flags_str}|{s['schema']}|{s['user']}|{s['example']}"
        )

    # 提取 Top SQL 涉及的表名，供后续拉取真实表结构使用
    top_sqls = [
        s['example']
        for s in sorted(pattern_stats.values(), key=lambda x: -x['total_time'])[:25]
    ]
    tables = extract_tables(top_sqls)
    print("=== TABLES ===")
    for t in tables:
        print(t)

    # 按 schema 分组的表名，供展示用
    schema_tables: dict = defaultdict(set)
    for _, s in sorted(pattern_stats.items(), key=lambda x: -x[1]['total_time'])[:25]:
        tbls = extract_tables([s['example']])
        schema = s.get('schema') or '(none)'
        for t in tbls:
            schema_tables[schema].add(t)
    print("=== TABLES_BY_SCHEMA ===")
    for schema in sorted(schema_tables.keys()):
        print(f"{schema}|{','.join(sorted(schema_tables[schema]))}")


if __name__ == '__main__':
    main()
