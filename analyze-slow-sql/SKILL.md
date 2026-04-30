---
name: analyze-slow-sql
description: 分析 MySQL 慢查询日志并输出结构化结果（含统计分布、Top SQL、诊断信号与辅助脚本）。
argument-hint: [/path/to/slow.log]
allowed-tools: Bash(python3:*), Bash(ls:*), Bash(find:*), Bash(wc:*), Bash(head:*), Bash(grep:*), Bash(mysql:*)
---

# MySQL 慢查询日志分析

## 用法

- 直接指定日志文件：

```bash
python3 <skill_dir>/scripts/analyze_slow_sql.py /path/to/slow.log
```

- 不确定日志文件位置时，可在当前目录扫描：

```bash
find . -maxdepth 2 \( -name "*.log*" -o -name "*slow*" \) -type f 2>/dev/null | head -20
```

## 输出说明（脚本 stdout）

脚本会输出若干分段块（例如 SUMMARY / DISTRIBUTION / USERS / SCHEMAS / TOP_* / DAILY / SUGGESTIONS / TABLES）。

## 进阶（可选）

该目录下还提供：

- `scripts/fetch_schema.py`：连接本地开发/仿真库抓取表结构（需要 mysql CLI）
- `scripts/gen_test_data.py`：根据表结构生成测试数据 INSERT SQL
- `scripts/generate_html_report.py` + `scripts/report_template.html`：将报告正文组装为 HTML

更完整的交互流程参考：`commands/analyze-slow-sql.md`。
