# 宁好 NingHao

**以宁德时代海外业务视角，实时解读全球储能、AI 数据中心与新能源政策的 AI 情报流。**

宁好不是新闻聚合器。它读完每一条新闻后回答一个问题：**这件事对宁德时代的海外生意意味着什么？**
然后把答案写成一张情报卡，附上原文配图和链接，有新消息就播报。

> 个人作品集项目，基于公开信息，不代表宁德时代官方立场。

---

## 它做什么

| 原文标题 | 宁好的标题 |
|---|---|
| PowerX signs pact with Energy Vault Japan on 1.5 GWh US BESS supply | 日本PowerX拟向美供1.5GWh储能，主打FEOC合规 |
| BMW Adds Samsung SDI, LG Energy Solution for Gen6 | 宝马Gen6电池扩充韩系供应商，美国份额给到LG |
| NTPC Green Energy tenders 10 GW/40 GWh of battery systems in India | 印度NTPC启动40GWh储能全球招标，指定LFP集装箱 |

每张情报卡包含：
- **分类**：项目动态、政策法规、财务披露、话事人发言、竞争格局、市场数据
- **信号与影响分**：机会、风险或中性，影响分 1–5
- **为什么重要**：和宁德时代海外业务的关系
- **原文要点**：只摘录原文里有的事实，不编造数字
- **建议动作**：给内部同事的一句话建议
- **原文**：原标题、来源、配图和链接，方便核对

## 工作原理

```mermaid
flowchart LR
  A[感知<br/>RSS · Google 新闻 · 联邦公报] --> B[补全<br/>原文链接 · 正文 · 配图]
  B --> C[判断<br/>Claude + 宁德时代视角]
  C --> D[记忆<br/>去重 · feed.json]
  D --> E[行动<br/>网站播报 · 飞书/企业微信推送]
  T((每 30 分钟<br/>GitHub Actions)) --> A
```

| 层 | 文件 | 用到的开源组件 |
|---|---|---|
| 感知 | `ninghao/fetch.py`、`config/sources.yaml` | feedparser、美国联邦公报 API |
| 补全 | `ninghao/enrich.py` | trafilatura（正文和 og:image）、googlenewsdecoder |
| 判断 | `ninghao/analyze.py`、`config/lens.md` | Anthropic Python SDK（结构化输出） |
| 记忆 | `ninghao/store.py` | 用 JSON 文件代替数据库，提交回仓库（git scraping 模式） |
| 行动 | `site/`、`ninghao/notify.py` | GitHub Pages；前端是纯 HTML/CSS/JS，无需构建 |

为什么这样设计，见 [docs/01_第一性原理.md](docs/01_第一性原理.md)。
想学 AI agent 怎么搭，见 [docs/02_AI-Agent入门.md](docs/02_AI-Agent入门.md)。

## 本地运行

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

只抓取、不调用 Claude，用来检查信息源是否正常：

```bash
.venv/bin/python -m ninghao.run --dry-run
```

正式运行，需要 Anthropic API key：

```bash
export ANTHROPIC_API_KEY=你的key
.venv/bin/python -m ninghao.run --max 5
```

在本地预览网站：

```bash
python3 -m http.server 8000 --directory site
```

然后用浏览器打开 http://localhost:8000。

## 部署到 GitHub（免费）

1. 在仓库的 **Settings → Secrets and variables → Actions** 里添加 `ANTHROPIC_API_KEY`。
2. 在 **Settings → Pages** 里，把 Source 设为 **GitHub Actions**。
3. 打开 **Actions → 宁好 · 抓取、分析与发布 → Run workflow**，手动运行一次。

之后每 30 分钟会自动运行一次。新情报会存回仓库，网站会自动更新；页面每分钟检查一次，有新内容就弹出提示。

**可选：推送到群聊。** 添加 `NOTIFY_WEBHOOK_URL` 密钥，填飞书或企业微信群机器人的 webhook 地址。影响分 ≥ 4 的情报会推送到群里。

## 定制

- **加信息源**：在 `config/sources.yaml` 里加一段，不用改代码。
- **改判断标准**：改 `config/lens.md`。这份文件就是宁好的「岗位说明书」，会原样放进 Claude 的系统提示词。
- **换模型或推理强度**：设置环境变量 `NINGHAO_MODEL`（默认 `claude-opus-5-5`）和 `NINGHAO_EFFORT`（`low`、`medium`、`high`，默认 `medium`）。

## 费用

每条新闻调用一次 Claude，用默认的 Claude Opus 5.5、medium 推理强度，大约 2–3 美分一条。每天处理 50–100 条新内容，一天约 1–3 美元。

两个控制费用的设计：
- 关键词预筛：明显无关的条目不会交给 Claude。
- `max_new_per_run` 限制每次运行最多分析多少条。

GitHub Actions 和 Pages 对公开仓库免费。

## 已知局限

- Energy-Storage.news 等少数网站拒绝程序抓取正文，这类条目只能根据标题和摘要判断，也没有配图（页面会显示分类占位图）。
- GitHub 的定时任务可能延迟几分钟，所以是「近实时」，不是秒级。
- 首批 18 条示例情报是开发时离线生成的，详情页会标注「种子数据」。接上 API key 运行后，会被正式分析的结果替换。

## 声明

标题与解读由 AI 生成，可能有误，请以原文为准。配图通过原媒体链接直接显示，版权归原媒体所有。
