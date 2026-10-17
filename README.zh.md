# checkup-engine

面向中小企业网站的开源 **AI 就绪度体检**。

> 早期版本（v0.1）。评分规则和采集器已经能用；公开 Demo 是「薄 Worker + 网关 VM 上的小服务」。请按早期项目预期。

## 做什么

1. 抓取公开网站（首页 + 若干关键页），遵守 `robots.txt`。
2. 按公开、可复现的 [五维评分规则](docs/rubric.md) 打分。
3. （可选）让大模型写 **最多 3 条建议**，每条必须引用实际抓到的证据 URL；质检会丢掉没有证据的说法。
4. 输出中英双语 HTML 报告。

## 快速开始

```bash
python3 -m checkup_engine https://example.com --lang zh --offline --out report.html
```

只需 Python 3.10+ 标准库。VM 部署见 [`service/DEPLOY.md`](service/DEPLOY.md)。

公开 Demo 限额：全站 **12 次/天**，每 IP **3 次/天**（北京时间 08:00 重置）。

## 许可

MIT © 2026 TalentOS

---

Maintained by [TalentOS](https://www.agentbay.asia) · 需要定制 Agent / 技能开发？[找我们定制 / Work with us](https://www.agentbay.asia/contact) · talentos@agentbay.asia
