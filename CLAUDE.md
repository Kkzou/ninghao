# 宁好 NingHao：项目规则

以宁德时代海外业务视角，实时解读储能、AI 数据中心与新能源政策的 AI 情报流。架构说明见 README.md，设计思路见 docs/01_第一性原理.md。

## 结构

- `config/sources.yaml`：信息源。加源只改这里。
- `config/lens.md`：判断标准，会原样放进 Claude 的系统提示词。
- `ninghao/`：管线，按「抓取 → 补全 → 判断 → 存储 → 推送」的顺序，入口是 `run.py`。
- `site/`：纯静态前端，读 `site/data/feed.json`。不引入框架，不加构建步骤。
- `data/state.json`：已处理条目的 ID，用于去重。

## 怎么验证改动

- 改了抓取或信息源：`.venv/bin/python -m ninghao.run --dry-run`
- 改了提示词或分析：`.venv/bin/python -m ninghao.run --max 5`（需要 ANTHROPIC_API_KEY，会花钱）
- 改了前端：`python3 -m http.server 8000 --directory site`，在桌面宽度和 375px 手机宽度下都检查一遍

## 硬性规则

- 情报卡里的事实（数字、公司名、日期）必须来自原文。不允许改提示词去放宽这一条。
- 模型默认 `claude-opus-5-5`，可以用环境变量 `NINGHAO_MODEL` 切换。不要在代码里写死其他模型。
- 不要提交 `.venv/`、`.env` 或任何 API key。
- 深蓝色主题，颜色统一用 `site/style.css` 里 `:root` 定义的变量。
- 页面和文档面向中文读者，用简体中文。
