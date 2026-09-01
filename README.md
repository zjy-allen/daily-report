# 每日日报（云端版）

每天北京时间 8:00 由 GitHub Actions 自动抓取公开新闻源，生成手机友好的日报网页并发布到 GitHub Pages。

## 板块与来源

| 板块 | 来源 |
|---|---|
| 🇨🇳 国家大事 | 中国新闻网滚动新闻 RSS |
| 🌍 世界大事 | 联合早报国际频道 + 中新网国际频道 |
| 💰 财经大事 | 华尔街见闻 RSS |
| 🤖 AI 动态 | 量子位 RSS |

纯聚合版：每条新闻为「标题 + 日期 + 原文链接」。

## 使用

- 手机访问仓库的 GitHub Pages 地址即可（见仓库 Pages 设置 / Actions 部署日志）。
- 每期归档在 `archive/YYYY-MM-DD.html`，入口页 `index.html` 永远是最新一期。
- 手动触发：Actions → daily-report → Run workflow。

## 定时说明

工作流 cron 为 UTC 0:00（北京 8:00）。GitHub 的计划任务可能延迟几分钟到半小时。
