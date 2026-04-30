#!/usr/bin/env python3
"""
HTML 报告组装脚本

将 AI 生成的报告正文嵌入到样式模板（report_template.html）中。
正文内容可从文件读取（--body-file）或从 stdin 读取（--stdin）。

用法：
  # 从 stdin 读取（推荐，无需临时文件）
  python3 generate_html_report.py \
    --template <script_dir>/report_template.html \
    --stdin \
    --log-file slow.log \
    --connected-db no << 'REPORT_BODY_EOF'
  <div class="report-header">...</div>
  REPORT_BODY_EOF

  # 从文件读取（兼容旧方式）
  python3 generate_html_report.py \
    --template <script_dir>/report_template.html \
    --body-file /path/to/report_body.html \
    --log-file slow.log \
    --connected-db yes
"""
import argparse
import os
import sys
from datetime import datetime


def main() -> None:
    parser = argparse.ArgumentParser(description='组装 HTML 慢查询分析报告')
    parser.add_argument('--template', required=True, help='report_template.html 路径')
    parser.add_argument('--body-file', default=None, help='AI 生成的报告正文 HTML 片段路径')
    parser.add_argument('--stdin', action='store_true', help='从 stdin 读取报告正文（与 --body-file 互斥）')
    parser.add_argument('--log-file', default='', help='慢日志文件名（用于标题）')
    parser.add_argument(
        '--connected-db',
        choices=['yes', 'no'],
        default='no',
        help='是否连接过数据库（yes 时追加账号清理提示）',
    )
    parser.add_argument('--output', default=None, help='输出文件路径（默认自动生成）')
    args = parser.parse_args()

    if args.stdin and args.body_file:
        print("ERROR: --stdin 与 --body-file 不能同时使用", file=sys.stderr)
        sys.exit(1)
    if not args.stdin and not args.body_file:
        print("ERROR: 必须指定 --stdin 或 --body-file 之一", file=sys.stderr)
        sys.exit(1)

    try:
        with open(args.template, 'r', encoding='utf-8') as f:
            template = f.read()
    except FileNotFoundError:
        print(f"ERROR: 模板文件不存在: {args.template}", file=sys.stderr)
        sys.exit(1)

    if args.stdin:
        body = sys.stdin.read()
    else:
        try:
            with open(args.body_file, 'r', encoding='utf-8') as f:
                body = f.read()
        except FileNotFoundError:
            print(f"ERROR: 报告正文文件不存在: {args.body_file}", file=sys.stderr)
            sys.exit(1)

    if not body.strip():
        print("ERROR: 报告正文内容为空", file=sys.stderr)
        sys.exit(1)

    # 估算输出 token（中英混合约 3 字节/token）
    est_tokens = len(body) // 3
    token_est = f'预估输出 ~{est_tokens:,} tokens'

    now = datetime.now()
    ts = now.strftime('%Y%m%d%H%M%S')
    log_name = os.path.basename(args.log_file) if args.log_file else '慢查询日志'
    # 取第一个 '.' 之前的部分，避免 mysql-slow.log.000008 → stem 含 .log
    log_stem = log_name.split('.')[0] if args.log_file else 'slowlog'

    html = (
        template.replace('{{LOG_FILE}}', log_name)
        .replace('{{TIMESTAMP}}', now.strftime('%Y-%m-%d %H:%M:%S'))
        .replace('{{TOKEN_EST}}', token_est)
        .replace('{{REPORT_BODY}}', body)
    )

    output_path = args.output or f"analysis_{log_stem}_{ts}.html"
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"✅ 报告已生成: {os.path.abspath(output_path)}")


if __name__ == '__main__':
    main()
