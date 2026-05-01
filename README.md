# Skills

这个仓库包含可复用的 Agent Skills（可通过 `skills` CLI 安装）。

## 安装

```bash
npx skills add dev4java/skills
```

## Skills 列表

### analyze-slow-sql

- **关键词**：slow sql / MySQL slow query log / SQL performance
- **用途**：解析 MySQL 慢查询日志，输出结构化统计（耗时分布、Top SQL、按用户/Schema/日趋势等），并提供诊断信号与配套脚本（可选：抓取表结构、生成测试数据、组装 HTML 报告）。
- **入口**：`analyze-slow-sql/SKILL.md`

