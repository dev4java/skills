#!/usr/bin/env python3
"""
测试数据生成脚本

根据 fetch_schema.py 输出的表结构，生成 INSERT SQL 测试数据。

用法：
  # 按数量生成（每表 1000 行）
  python3 gen_test_data.py --schema-file schema.txt --tables "orders,users" --count 1000

  # 按日期范围生成（指定日期列，生成日期在范围内的随机数据）
  python3 gen_test_data.py --schema-file schema.txt --tables "orders" \
      --date-col created_at --start-date 2024-01-01 --end-date 2024-12-31 --count 500

  --schema-file 为 fetch_schema.py --fetch 的输出文件（包含 === SCHEMA_DATA === 块）
  --output      指定输出 SQL 文件，默认输出到 test_data_<timestamp>.sql
"""
import argparse
import random
import re
import string
import sys
from datetime import date, datetime, timedelta


# ── 解析 fetch_schema.py 的输出 ────────────────────────────────────────────


def parse_schema_file(path: str) -> dict[str, str]:
    """从 fetch_schema.py 输出文件中提取各表的 CREATE TABLE DDL。"""
    try:
        with open(path, 'r', errors='replace') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"ERROR: schema 文件不存在: {path}", file=sys.stderr)
        sys.exit(1)

    tables: dict[str, str] = {}
    current_table: str | None = None
    collecting_ddl = False
    ddl_lines: list[str] = []

    for line in content.splitlines():
        m = re.match(r'^--- TABLE: (\S+) ---', line)
        if m:
            if current_table and ddl_lines:
                tables[current_table] = '\n'.join(ddl_lines)
            current_table = m.group(1)
            collecting_ddl = False
            ddl_lines = []
            continue

        if line.strip() == 'CREATE_SQL:':
            collecting_ddl = True
            continue

        if collecting_ddl:
            # 遇到下一个 KEY: 行时停止
            if re.match(r'^[A-Z_]+:', line):
                collecting_ddl = False
            else:
                ddl_lines.append(line)

    if current_table and ddl_lines:
        tables[current_table] = '\n'.join(ddl_lines)

    return tables


# ── 解析 CREATE TABLE DDL ──────────────────────────────────────────────────


_RE_COL = re.compile(
    r'^\s*`([^`]+)`\s+(\w+)(?:\(([^)]+)\))?([^,]*)',
    re.IGNORECASE,
)
_RE_ENUM = re.compile(r"'([^']*)'", re.IGNORECASE)


def parse_columns(ddl: str) -> list[dict]:
    """从 CREATE TABLE DDL 中提取列名、类型、约束信息。"""
    columns: list[dict] = []
    for line in ddl.splitlines():
        line = line.strip().rstrip(',')
        if line.upper().startswith(('PRIMARY', 'UNIQUE', 'KEY', 'INDEX', 'CONSTRAINT', 'ENGINE', ')')):
            continue
        m = _RE_COL.match(line)
        if not m:
            continue
        name, col_type, type_arg, extras = m.group(1), m.group(2).upper(), m.group(3), m.group(4)
        not_null = 'NOT NULL' in extras.upper()
        auto_inc = 'AUTO_INCREMENT' in extras.upper()
        enum_vals = _RE_ENUM.findall(type_arg or '') if col_type == 'ENUM' else []
        columns.append(
            {
                'name': name,
                'type': col_type,
                'type_arg': type_arg or '',
                'not_null': not_null,
                'auto_increment': auto_inc,
                'enum_vals': enum_vals,
            }
        )
    return columns


# ── 随机值生成 ─────────────────────────────────────────────────────────────


def _rand_str(max_len: int) -> str:
    length = random.randint(1, min(max_len, 32))
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


def _rand_date(start: date, end: date) -> date:
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, max(delta, 0)))


def _rand_datetime(start: date, end: date) -> datetime:
    d = _rand_date(start, end)
    return datetime(
        d.year,
        d.month,
        d.day,
        random.randint(0, 23),
        random.randint(0, 59),
        random.randint(0, 59),
    )


def generate_value(col: dict, row_index: int, date_col: str | None, start: date, end: date) -> str:
    """为单个列生成一个 SQL 字面量值。"""
    name = col['name']
    col_type = col['type']

    if col['auto_increment']:
        return str(row_index + 1)

    # 日期范围列：使用指定范围内的随机时间
    is_date_col = date_col and name.lower() == date_col.lower()

    if col_type in ('DATE',):
        d = _rand_date(start, end) if is_date_col else _rand_date(date(2020, 1, 1), date(2025, 12, 31))
        return f"'{d.isoformat()}'"

    if col_type in ('DATETIME', 'TIMESTAMP'):
        dt = _rand_datetime(start, end) if is_date_col else _rand_datetime(date(2020, 1, 1), date(2025, 12, 31))
        return f"'{dt.strftime('%Y-%m-%d %H:%M:%S')}'"

    if col_type in ('TINYINT', 'SMALLINT', 'MEDIUMINT', 'INT', 'INTEGER', 'BIGINT'):
        arg = col['type_arg']
        if arg == '1':
            return str(random.randint(0, 1))
        return str(random.randint(1, 999999))

    if col_type in ('FLOAT', 'DOUBLE', 'DECIMAL', 'NUMERIC'):
        return f"{random.uniform(0.01, 9999.99):.2f}"

    if col_type == 'ENUM':
        vals = col['enum_vals']
        if vals:
            return f"'{random.choice(vals)}'"
        return "'value'"

    if col_type in ('CHAR', 'VARCHAR'):
        try:
            max_len = int(col['type_arg'])
        except (ValueError, TypeError):
            max_len = 64
        return f"'{_rand_str(max_len)}'"

    if col_type in ('TEXT', 'MEDIUMTEXT', 'LONGTEXT', 'TINYTEXT'):
        return f"'{_rand_str(200)}'"

    if col_type in ('TINYBLOB', 'BLOB', 'MEDIUMBLOB', 'LONGBLOB'):
        return "0x00"

    if col_type == 'JSON':
        return """'{"key":"value"}'"""

    if col_type in ('BOOLEAN', 'BOOL'):
        return str(random.randint(0, 1))

    # 兜底：空字符串或 NULL
    return 'NULL' if not col['not_null'] else "''"


# ── 生成 INSERT SQL ────────────────────────────────────────────────────────


def generate_inserts(
    table: str,
    ddl: str,
    count: int,
    date_col: str | None,
    start: date,
    end: date,
    batch_size: int = 500,
) -> list[str]:
    columns = parse_columns(ddl)
    if not columns:
        print(f"WARN: 无法解析表 {table} 的列信息，跳过", file=sys.stderr)
        return []

    col_names = ', '.join(f'`{c["name"]}`' for c in columns)
    lines: list[str] = [f"-- 表: {table}  行数: {count}  生成时间: {datetime.now():%Y-%m-%d %H:%M:%S}"]

    rows_buf: list[str] = []
    for i in range(count):
        vals = ', '.join(generate_value(c, i, date_col, start, end) for c in columns)
        rows_buf.append(f"  ({vals})")

        if len(rows_buf) == batch_size or i == count - 1:
            lines.append(f"INSERT INTO `{table}` ({col_names}) VALUES")
            lines.append(',\n'.join(rows_buf) + ';')
            rows_buf = []

    return lines


# ── 主入口 ─────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description='根据表结构生成测试数据 INSERT SQL')
    parser.add_argument('--schema-file', required=True, help='fetch_schema.py --fetch 的输出文件路径')
    parser.add_argument('--tables', required=True, help='逗号分隔的表名，需与 schema-file 中的表名一致')
    parser.add_argument('--count', type=int, default=100, help='每表生成的行数（默认 100）')
    parser.add_argument(
        '--date-col',
        default=None,
        help='日期列名，指定后该列的值将落在 start-date ~ end-date 范围内',
    )
    parser.add_argument('--start-date', default='2024-01-01', help='日期范围起始（格式 YYYY-MM-DD，默认 2024-01-01）')
    parser.add_argument('--end-date', default='2024-12-31', help='日期范围结束（格式 YYYY-MM-DD，默认 2024-12-31）')
    parser.add_argument('--output', default=None, help='输出 SQL 文件路径（默认 test_data_<timestamp>.sql）')
    args = parser.parse_args()

    tables = [t.strip() for t in args.tables.split(',') if t.strip()]
    if not tables:
        print("ERROR: --tables 不能为空", file=sys.stderr)
        sys.exit(1)

    try:
        start_date = date.fromisoformat(args.start_date)
        end_date = date.fromisoformat(args.end_date)
    except ValueError as e:
        print(f"ERROR: 日期格式错误 — {e}", file=sys.stderr)
        sys.exit(1)

    if start_date > end_date:
        print("ERROR: start-date 不能晚于 end-date", file=sys.stderr)
        sys.exit(1)

    schema_map = parse_schema_file(args.schema_file)

    output_path = args.output or f"test_data_{datetime.now():%Y%m%d_%H%M%S}.sql"
    all_lines: list[str] = [
        "-- 测试数据 INSERT SQL",
        f"-- 生成参数: count={args.count}, date_col={args.date_col}, range={args.start_date}~{args.end_date}",
        "-- ⚠️  仅用于本地开发或仿真环境，严禁导入生产库",
        "SET FOREIGN_KEY_CHECKS = 0;",
        "",
    ]

    for table in tables:
        ddl = schema_map.get(table)
        if not ddl:
            print(f"WARN: schema-file 中未找到表 {table}，跳过", file=sys.stderr)
            continue
        lines = generate_inserts(table, ddl, args.count, args.date_col, start_date, end_date)
        all_lines.extend(lines)
        all_lines.append("")

    all_lines.append("SET FOREIGN_KEY_CHECKS = 1;")

    with open(output_path, 'w') as f:
        f.write('\n'.join(all_lines))

    print(f"✅ 已生成测试数据: {output_path}")
    print(f"   表: {', '.join(tables)}")
    print(f"   每表行数: {args.count}")
    if args.date_col:
        print(f"   日期列 {args.date_col} 范围: {args.start_date} ~ {args.end_date}")
    print("⚠️  请仅在本地开发或仿真环境中使用此数据，严禁导入生产库。")


if __name__ == '__main__':
    main()
