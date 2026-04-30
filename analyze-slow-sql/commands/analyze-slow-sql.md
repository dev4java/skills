---
description: 分析 MySQL 慢查询日志，输出结构化 HTML 报告。支持传入日志文件路径，或自动扫描当前目录。
argument-hint: [/path/to/slow.log]
allowed-tools: Bash(python3:*), Bash(ls:*), Bash(find:*), Bash(wc:*), Bash(mysql:*), Bash(head:*), Bash(grep:*), Bash(cat:*)
---

# MySQL 慢查询日志分析

## 启动时展示：当前流程总览

在执行任何步骤前，先向用户展示以下流程图，让用户了解整体进度和分支：

```
┌─────────────────────────────────────────────────────────────┐
│            MySQL 慢查询日志分析 — 执行流程                     │
└─────────────────────────────────────────────────────────────┘

  [1] 检查 Python 3 环境            ⏱ <5s
       │
  [2] 定位 skill 脚本               ⏱ <5s
       │
  [3] 确定慢日志文件                 ⏱ <5s
       │
  [4] 执行慢日志分析                 ⏱ 每10万行约5~10s
       │
  [5] 生成 HTML 分析报告             ⏱ 问题数 × ~30s
       │ Python 写盘，告知用户文件路径
       │
  [6] 是否连接本地开发/仿真数据库增强建议？
       │
       ├─── 1.跳过 ─────────────────────────────────────────┐
       │                                                     │
       └─── 2.连接                                           │
             │                                               │
        [6a] 检查 mysql CLI                                  │
             │                                               │
        [6b] 收集连接信息                                     │
             │ (host / port / schema)                        │
             │                                               │
        [6c] 检查/创建只读账号          ⏱ <5s               │
             │                                               │
        [6d] 拉取表结构                  ⏱ 5~30s            │
             │ (DDL / 索引 / 行数)                           │
             │                                               │
        [6e] 用真实表结构重新生成报告     ⏱ 问题数 × ~30s   │
             │ Python 覆盖写同一 HTML 文件                   │
             │                                               │
             └───────────────────────────────────────────────┘
                                          │
                                    [7] 是否生成测试数据验证优化建议？
                                          │ (仅当第6步获取了表结构时展示)
                                          │
                                    ├─── 1.跳过 ──────────────┐
                                    │                          │
                                    └─── 2.生成               │
                                          │                    │
                                    [7b] 生成 INSERT SQL       │
                                          │ (按数量/日期范围)  │
                                          └────────────────────┘
                                                    │
                                              [8] 告知最终报告路径 + 提示清理账号
```

> 当前处于：**第 1 步**，开始环境检查。

## 第 1 步：检查 Python 3 环境
> ⏱ 预估耗时：< 5 秒 | 📍 当前进度：[1/8]

在执行任何操作前，先检查本地是否有可用的 Python 3：

```bash
python3 --version 2>/dev/null || python --version 2>/dev/null
```

根据输出结果：

- **输出 `Python 3.x.x`** → 记录可用命令（`python3` 或 `python`），继续后续步骤
- **输出 `Python 2.x.x`** → Python 2 不支持，视为未安装，停止并提示用户
- **命令不存在** → 停止并提示用户按以下方式安装：

  | 系统 | 安装方式 |
  |------|---------|
  | macOS | `brew install python3` 或从 https://python.org 下载安装包 |
  | Ubuntu / Debian | `sudo apt install python3` |
  | CentOS / RHEL | `sudo yum install python3` 或 `sudo dnf install python3` |
  | Windows | 从 https://python.org 下载安装包，安装时勾选「Add to PATH」 |

  安装完成后请重新运行本命令。

后续所有 `python3` 命令均使用此步骤确认的可用命令。

## 第 2 步：定位 skill 脚本
> ⏱ 预估耗时：< 5 秒 | 📍 当前进度：[2/8]

本 skill 的分析脚本位于与本文件同级的 `scripts/` 目录。
使用 `find` 在 `~/.claude` 下定位：

```bash
find ~/.claude -name "analyze_slow_sql.py" 2>/dev/null | head -1
```

将该路径记为 `<script_dir>`，后续所有脚本均从此目录调用。

## 第 3 步：确定日志文件
> ⏱ 预估耗时：< 5 秒 | 📍 当前进度：[3/8]

如果用户传入了参数（如 `/analyze-slow-sql /path/to/slow.log`），直接使用该路径。

否则，扫描当前目录寻找慢查询日志：

```bash
find . -maxdepth 2 \( -name "*.log*" -o -name "*slow*" \) -type f 2>/dev/null | head -20
```

- 找到多个文件 → 以编号列表展示，让用户选择序号：
  > 找到以下日志文件，请选择：
  > **1.** /path/to/slow1.log
  > **2.** /path/to/slow2.log
  > ...
- 只有一个 → 直接使用
- 没有找到 → 提示用户：
  > 未找到慢查询日志文件。请选择：
  > **1.** 我来输入文件路径
  > **2.** 退出

## 第 4 步：检测日志格式并执行分析
> ⏱ 预估耗时：格式检测 <5 秒；每 10 万行分析约 5～10 秒 | 📍 当前进度：[4/8]

### 4a. 检测日志格式

确定日志文件后，**先**读取头部 50 行判断是否为 MySQL 慢查询日志格式，再执行分析：

```bash
head -50 <log_file> | grep -cE "# User@Host:|# Query_time:|# Time:"
```

根据输出：

- **结果 ≥ 2** → 确认为 MySQL 慢查询日志，告知用户"检测到 MySQL 慢查询日志格式，开始分析"，继续 4b
- **结果为 0 或 1** → 读取前 5 行展示给用户，并告知：

  > ⚠️ 未检测到 MySQL 慢查询日志特征（缺少 `# User@Host:`、`# Query_time:` 等字段）。
  >
  > 本 skill 仅支持 **MySQL / MariaDB 慢查询日志**格式（由 `slow_query_log=ON` 开启生成）。
  >
  > 如果您使用的是其他数据库（PostgreSQL、Oracle 等），本 skill 暂不支持。
  >
  > 请选择：
  > **1.** 提供正确的 MySQL 慢查询日志文件路径
  > **2.** 退出

### 4b. 执行分析

```bash
python3 <script_dir>/analyze_slow_sql.py <log_file>
```

如果日志文件超过 50 万行，先用 `wc -l` 确认行数并告知用户，再执行。

分析完成后：
- 解析 `=== TABLES ===` 得到表名列表，记为 `<tables>`
- 解析 `=== TABLES_BY_SCHEMA ===` 得到按数据库分组的表，格式为 `schema|table1,table2,...`
- 解析所有数据段备用（SUMMARY / DISTRIBUTION / USERS / SCHEMAS / DAILY / SUGGESTIONS）

## 第 5 步：生成 HTML 分析报告（经验规则版）
> 📍 当前进度：[5/8]（每个问题约 30 秒，问题越多耗时越长）

见「建议生成规则」和「HTML 报告正文结构参考」两节，基于经验规则生成报告正文 HTML。

**所有优先级（P0/P1/P2/P3）均完整输出 issue-block，不做简化或合并。**

**直接用 Bash heredoc 将内容 pipe 给 Python，无需任何临时文件：**

```bash
python3 <script_dir>/generate_html_report.py \
  --template <script_dir>/report_template.html \
  --stdin \
  --log-file <log_file_basename> \
  --connected-db no << 'REPORT_BODY_EOF'
<此处替换为完整的报告正文 HTML 片段，从 <div class="report-header"> 到 </script>，不含 html/head/body 标签>
REPORT_BODY_EOF
```

告知用户文件路径：`analysis_<慢日志文件名>_<时间戳>.html`，可直接用浏览器打开查看。

## 第 6 步：询问是否连接数据库增强建议（可选）
> ⏱ 预估耗时：< 5 秒 | 📍 当前进度：[6/8]

报告生成后，询问是否连接本地开发/仿真数据库拉取真实表结构（严禁连接生产环境）。
