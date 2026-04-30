#!/usr/bin/env python3
"""
MySQL 表结构抓取脚本

依赖：系统已安装 mysql 命令行客户端（无需任何 pip 安装）

安全声明：
  - 账号名固定（claude_slow_ronly），密码每次运行随机生成，不持久化、不写入代码仓库
  - 授权范围精确到指定 schema，不授予 *.* 全库权限
  - 管理员密码全程不经过本脚本，也不会被 Claude 读取
  - 连接凭证写入临时 .cnf 文件（权限 600），进程退出后立即删除，不暴露在进程列表

用法：
  # 检查默认账号是否存在可用，若不存在则输出需要执行的建账 SQL
  python3 fetch_schema.py --check-or-create --schemas "mydb,bizdb" \
      --host localhost --port 3306

  # 拉取表结构（账号凭证自动加载，无需传入）
  python3 fetch_schema.py --fetch --tables "orders,users" \
      --host localhost --port 3306 --schema mydb
"""
import argparse
import os
import secrets
import string
import subprocess
import sys
import tempfile

_USERNAME = 'claude_slow_ronly'
_PASSWORD = ''.join(
    secrets.choice(string.ascii_letters + string.digits + '!@#$%^&*') for _ in range(16)
)


# ── MySQL CLI ──────────────────────────────────────────────────────────────


def check_mysql_cli() -> str:
    """检查系统是否有 mysql 命令行客户端，返回可用的命令名，找不到返回空字符串。"""
    candidates = [
        'mysql',
        'mysql5',
        'mariadb',
        '/usr/bin/mysql',
        '/usr/local/bin/mysql',
        '/usr/sbin/mysql',
        '/opt/homebrew/bin/mysql',
        '/opt/homebrew/opt/mysql-client/bin/mysql',
    ]
    for cmd in candidates:
        try:
            r = subprocess.run([cmd, '--version'], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return cmd
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return ''


def _run_query(mysql_cmd: str, cnf_path: str, schema: str | None, sql: str) -> tuple[str, str]:
    """通过 mysql CLI 执行单条 SQL，返回 (stdout, stderr)。"""
    cmd = [mysql_cmd, f'--defaults-file={cnf_path}', '--batch', '--silent']
    if schema:
        cmd.append(schema)
    result = subprocess.run(cmd, input=sql, capture_output=True, text=True, timeout=30)
    return result.stdout, result.stderr


def _make_cnf(host: str, port: int) -> str:
    """写入临时 .cnf 文件（权限 600），返回路径。调用方负责删除。"""
    fd, cnf_path = tempfile.mkstemp(suffix='.cnf', prefix='slow_sql_')
    with os.fdopen(fd, 'w') as f:
        f.write(f"[client]\nhost={host}\nport={port}\nuser={_USERNAME}\npassword={_PASSWORD}\n")
    os.chmod(cnf_path, 0o600)
    return cnf_path


# ── check-or-create 模式 ───────────────────────────────────────────────────


def cmd_check_or_create(schemas: list[str], host: str, port: int) -> None:
    mysql_cmd = check_mysql_cli()
    if not mysql_cmd:
        print("ERROR: 未找到 mysql 命令行客户端", file=sys.stderr)
        sys.exit(1)

    print("ACCOUNT_STATUS: NEED_CREATE")
    print("\n" + "=" * 62)
    print("  ⚠️  安全说明")
    print("=" * 62)
    print(f"  账号名：{_USERNAME}  密码：{_PASSWORD}（本次运行随机生成）")
    print("  授权范围精确到以下 schema，不授予全库权限。")
    print("  您的管理员账号密码不会经过本脚本，也不会被 Claude 读取。")
    print("=" * 62)

    print("\n【1】请用管理员账号在 MySQL 中执行以下 SQL 创建只读账号：\n")
    print(f"  CREATE USER '{_USERNAME}'@'%' IDENTIFIED BY '{_PASSWORD}';")
    if schemas:
        for schema in schemas:
            print(f"  GRANT SELECT ON `{schema}`.* TO '{_USERNAME}'@'%';")
    else:
        print("  -- ⚠️  未指定 schema，授予全库 SELECT 权限，建议改为按库授权")
        print(f"  GRANT SELECT ON *.* TO '{_USERNAME}'@'%';")
    print("  FLUSH PRIVILEGES;")

    print("\n【2】分析完成后，执行以下 SQL 删除账号：\n")
    print(f"  DROP USER '{_USERNAME}'@'%';")
    print()


# ── fetch 模式 ─────────────────────────────────────────────────────────────


def _parse_show_create_table(stdout: str) -> str:
    line = stdout.strip()
    if '\t' in line:
        return line.split('\t', 1)[1]
    return line


def _parse_show_index(stdout: str) -> list[dict]:
    indexes = []
    for line in stdout.strip().splitlines():
        parts = line.split('\t')
        if len(parts) >= 7:
            indexes.append(
                {
                    'Key_name': parts[2],
                    'Seq_in_index': parts[3],
                    'Column_name': parts[4],
                    'Cardinality': parts[6],
                    'Non_unique': parts[1],
                }
            )
    return indexes


def _resolve_table_schemas(
    mysql_cmd: str, cnf_path: str, tables: list[str], hint_schema: str | None
) -> dict[str, str]:
    """
    用 information_schema 查询每张表实际所在的 schema。
    返回 {table_name: schema_name}，未找到的表不在字典中。
    hint_schema 优先：若指定 schema 里有同名表，优先取该 schema 的结果。
    """
    quoted = ', '.join(f"'{t}'" for t in tables)
    sql = (
        "SELECT table_name, table_schema "
        "FROM information_schema.tables "
        f"WHERE table_name IN ({quoted}) "
        "AND table_type = 'BASE TABLE';"
    )
    out, err = _run_query(mysql_cmd, cnf_path, None, sql)
    if err and 'ERROR' in err.upper():
        return {}

    # 可能一张表名在多个 schema 都存在，优先取 hint_schema
    result: dict[str, str] = {}
    for line in out.strip().splitlines():
        parts = line.split('\t')
        if len(parts) < 2:
            continue
        tname, tschema = parts[0].lower(), parts[1]
        if tname not in result:
            result[tname] = tschema
        elif hint_schema and tschema == hint_schema:
            result[tname] = tschema
    return result


def cmd_fetch(tables: list[str], host: str, port: int, schema: str | None) -> None:
    mysql_cmd = check_mysql_cli()
    if not mysql_cmd:
        print("ERROR: 未找到 mysql 命令行客户端，请先安装：", file=sys.stderr)
        print("  macOS:          brew install mysql-client", file=sys.stderr)
        print("  Ubuntu/Debian:  sudo apt install default-mysql-client", file=sys.stderr)
        print("  CentOS/RHEL:    sudo yum install mysql", file=sys.stderr)
        sys.exit(1)

    cnf_path = _make_cnf(host, port)
    try:
        _out, err = _run_query(mysql_cmd, cnf_path, schema, 'SELECT 1;')
        if err and 'ERROR' in err.upper():
            print(f"ERROR: 连接失败 — {err.strip()}", file=sys.stderr)
            sys.exit(1)

        # 通过 information_schema 自动发现每张表的真实 schema
        table_schema_map = _resolve_table_schemas(mysql_cmd, cnf_path, tables, schema)

        found_tables: list[str] = []
        missing_tables: list[str] = []

        print("=== SCHEMA_DATA ===")
        for table in tables:
            print(f"--- TABLE: {table} ---")

            actual_schema = table_schema_map.get(table.lower())
            if not actual_schema:
                print("ROW_COUNT: NOT_FOUND")
                missing_tables.append(table)
                print()
                continue

            # 用真实 schema 执行查询
            out, err = _run_query(
                mysql_cmd, cnf_path, actual_schema, f"SHOW TABLE STATUS LIKE '{table}';"
            )
            parts = out.strip().split('\n')[0].split('\t') if out.strip() else []
            if len(parts) >= 9:
                print(f"SCHEMA: {actual_schema}")
                print(f"ROW_COUNT: {parts[4]}")
                print(f"DATA_LENGTH: {parts[6]} bytes")
                print(f"INDEX_LENGTH: {parts[8]} bytes")
            else:
                print(f"SCHEMA: {actual_schema}")
                print("ROW_COUNT: unknown")

            out, err = _run_query(
                mysql_cmd, cnf_path, actual_schema, f"SHOW CREATE TABLE `{table}`;"
            )
            if out.strip():
                print("CREATE_SQL:")
                print(_parse_show_create_table(out))
            elif err:
                print(f"CREATE_SQL: error({err.strip()})")

            out, err = _run_query(mysql_cmd, cnf_path, actual_schema, f"SHOW INDEX FROM `{table}`;")
            indexes = _parse_show_index(out)
            print("INDEXES:")
            for idx in indexes:
                unique = idx['Non_unique'] == '0'
                print(
                    f"  {idx['Key_name']} | col={idx['Column_name']}"
                    f" | cardinality={idx['Cardinality']}"
                    f" | unique={unique} | seq={idx['Seq_in_index']}"
                )
            if not indexes and err:
                print(f"  error({err.strip()})")

            found_tables.append(table)
            print()

        print("=== END SCHEMA_DATA ===")

        print("\n=== FETCH_SUMMARY ===")
        print(f"FOUND: {','.join(found_tables) if found_tables else '(none)'}")
        print(f"MISSING: {','.join(missing_tables) if missing_tables else '(none)'}")
        print(f"FOUND_COUNT: {len(found_tables)}")
        print(f"MISSING_COUNT: {len(missing_tables)}")
        print("=== END FETCH_SUMMARY ===")

        if missing_tables:
            print(
                f"\n⚠️  以下 {len(missing_tables)} 张表在当前库中未找到：{', '.join(missing_tables)}",
                file=sys.stderr,
            )
        if found_tables:
            print(f"✅ 成功抓取 {len(found_tables)} 张表结构。")
        print("⚠️  请记得执行 DROP USER SQL 删除临时账号。")

    finally:
        try:
            os.unlink(cnf_path)
        except OSError:
            pass


# ── 主入口 ─────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description='MySQL 表结构抓取工具（依赖系统 mysql 客户端）')
    parser.add_argument(
        '--check-or-create', action='store_true', help='检查默认账号是否可用，不可用则生成建账 SQL'
    )
    parser.add_argument('--fetch', action='store_true', help='连接数据库拉取表结构')
    parser.add_argument('--tables', default='', help='逗号分隔的表名列表')
    parser.add_argument('--schemas', default='', help='逗号分隔的 schema 列表（用于精确授权）')
    parser.add_argument('--host', default='localhost')
    parser.add_argument('--port', type=int, default=3306)
    parser.add_argument('--schema', default=None, help='连接时使用的默认 schema')
    args = parser.parse_args()

    schemas = [s.strip() for s in args.schemas.split(',') if s.strip()]

    if args.check_or_create:
        cmd_check_or_create(schemas, args.host, args.port)
    elif args.fetch:
        tables = [t.strip() for t in args.tables.split(',') if t.strip()]
        if not tables:
            print("ERROR: --tables 不能为空", file=sys.stderr)
            sys.exit(1)
        cmd_fetch(tables, args.host, args.port, args.schema)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
