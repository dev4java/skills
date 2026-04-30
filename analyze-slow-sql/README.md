---
description: 分析 MySQL 慢查询日志，输出结构化报告。支持传入日志文件路径，或自动扫描当前目录。
allowed-tools: Bash(python3:*), Bash(ls:*), Bash(find:*), Bash(wc:*)
---

# MySQL 慢查询日志分析

## 确定日志文件

如果用户传入了参数（如 `/analyze-slow-sql /path/to/slow.log`），直接使用该路径。

否则，扫描当前目录寻找慢查询日志：

```
!find . -maxdepth 2 \( -name "*.log*" -o -name "*slow*" \) -type f 2>/dev/null | head -20
```

如果找到多个文件，告知用户并让其选择；如果只有一个，直接使用；如果没有找到，提示用户提供文件路径。

## 执行分析

确定日志文件后，找到本 skill 所在目录下的 `scripts/analyze_slow_sql.py`，运行：

```bash
python3 <skill_dir>/scripts/analyze_slow_sql.py <log_file>
```

其中 `<skill_dir>` 是本 skill 安装后的实际路径（通常为 `~/.claude/skills/analyze-slow-sql` 或 `~/.claude/commands/analyze-slow-sql`），`<log_file>` 为确定的日志文件路径。

如果日志文件超过 50 万行，先用 `wc -l` 确认行数并告知用户，再执行脚本（脚本本身按行读取，不会加载全部内容到内存）。

## 生成报告

根据脚本输出的结构化数据，生成完整的 Markdown 分析报告，内容包含：

1. **总体概况** — 条数、累计/平均/最大耗时、时间跨度
2. **耗时分布** — 各耗时区间的条数占比
3. **按用户统计** — 各账号的次数、总耗时、最大单次耗时
4. **按 Schema 统计** — 各数据库的次数与耗时占比
5. **按日趋势** — 最近 30 天每日条数与耗时（标注异常突发日）
6. **核心问题逐项分析**（按总耗时 Top 排序）：
   - 每个问题给出根因判断（锁等待 / 全表扫描 / 索引缺失 / 表膨胀 / 高并发等）
   - 提供具体可执行的 SQL 优化建议
7. **全表扫描 Top 10**（按 max_rows_examined）
8. **优化建议优先级汇总表**（P0/P1/P2/P3 四级）
9. **慢查询 SQL 模式 Top 25**（附完整数据表格）

## 保存报告

将报告保存为 `slow_sql_analysis_report.md`，与日志文件放在同一目录下，并告知用户报告路径。

## 注意事项

- `rows_examined` 极大但耗时极短的 → 索引缺失，建议 `EXPLAIN`。
- `rows_examined` 极小但耗时极长的 → 锁等待，建议排查事务。
- 多条不同表的 DML 同一时刻卡住相同时长 → MDL 锁或长事务阻塞，标记为 P0。
- 来自 DBeaver 的 `LIKE '%x%'` 查询 → 前导通配符全表扫描，归为 DBA 操作规范问题。
