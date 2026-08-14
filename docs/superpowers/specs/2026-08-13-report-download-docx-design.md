# 报告下载为 Word 设计(ReportModal 统一下载入口)

日期:2026-08-13
状态:已确认(生成位置/转换保真度/文件名规则均经用户确认)

## 背景

用户要求:每个查看诊断报告的入口(实时摘要卡、复盘摘要卡、历史结果内的报告按钮、复盘审核弹窗的查看报告)打开报告后,都能下载为 Word 文档。

关键事实:**所有报告查看均汇聚到 `ReportModal.vue`**(store.reportModal = { title, content }):
- `ReportViewer.vue` SummaryCard.openReport(实时/复盘摘要卡「查看报告」)
- `HistoryView.vue` viewReport(历史记录「实时诊断报告」「复盘报告 N」按钮)
- `ReportReviewModal.vue` viewReport(复盘审核期「查看报告」)

报告内容为 Markdown,结构简单:`## 章节` 标题、`-` 列表、`**粗体**`、`---`(conclusion 代码块在 vendor 已剥离,不会出现在 report 字段)。

## 设计

### 1. 纯前端生成(不动 backend / vendor)

新依赖:`docx`(npm,浏览器端生成 .docx)。新增工具模块 `frontend/src/reportDocx.js`:

- `downloadReportDocx(title, content, meta)`:
  1. Markdown → docx 段落数组(见 §2 转换规则)
  2. `new Document({ sections: [{ children }] })`,`Packer.toBlob(doc)`
  3. 创建 `<a download>` + `URL.createObjectURL` 触发下载,随后 revoke
- 文件名:`{标题}_{线路名}_{故障时间}_{生成时间戳}.docx`
  - 生成时间戳:本地时间 `YYYYMMDD_HHmm`(pad 补零,与 ws.js openSaveNaming 同例)
  - 非法文件名字符 `[\\/:*?"<>|]` 替换为 `-`;字段缺失时略去该段(不留下连续下划线)
  - 例:`实时诊断报告_雅湖线_2026-08-12 14:30_20260813_1532.docx`(标题本身含实时/复盘语义)

### 2. Markdown → Word 转换规则(与弹窗 renderMd 同级)

| Markdown | Word |
|---|---|
| `# / ## / ### ` | HeadingLevel.HEADING_1/2/3 |
| `- ` 连续行 | 项目符号列表(bullet) |
| `**text**` 行内 | bold TextRun(其余文本普通 run) |
| `---` | 空段落(视觉分隔) |
| 其他一切(含代码块、表格语法) | 纯文本段落 |

逐行扫描;空行跳过(段落间距由 docx 样式承担)。

### 3. reportModal meta 扩展

`store.reportModal = { title, content, meta? }`,`meta = { line, faultTime }` 可选。三处入口补传:

- **SummaryCard.openReport**(ReportViewer.vue):`meta: { line: props.data?.summary?.line_name, faultTime: props.data?.summary?.fault_time }`
- **HistoryView.viewReport**:签名改为 `viewReport(title, content, summary)`;line 取 `store.recordDetail.line`,faultTime 取 `summary?.fault_time`(realtime/replays[i] 均存了 summary,records.py:52-57);审核期回退无 meta
- **ReportReviewModal.viewReport**:`meta: { line: store.summaries.replay?.summary?.line_name || store.currentLine, faultTime: store.summaries.replay?.summary?.fault_time }`

meta 缺失时文件名退化为 `{标题}_{生成时间戳}.docx`,下载功能本身不受影响。

### 4. 下载按钮(ReportModal.vue)

标题栏关闭 × 左侧加「下载 Word」按钮(样式仿既有边框按钮,cyan),点击调 `downloadReportDocx(store.reportModal.title, store.reportModal.content, store.reportModal.meta)`。content 为空时按钮禁用。

## 不做的事

- Word 样式深度定制(页眉/页脚/logo/字体主题)
- 比对弹窗(CompareModal)导出
- backend / vendor 任何改动
- Markdown 表格/代码块的 Word 保真转换(报告实际不含)

## 测试

前端无测试框架:`npm run build` 通过 + 人工核对:
1. 实时摘要卡「查看报告」→ 下载 → Word 打开,标题层级/列表/粗体正确,文件名含线路名+故障时间
2. 复盘摘要卡同上
3. 历史结果页两个报告按钮 → 下载,文件名含该记录线路名
4. 复盘审核期「查看报告」→ 下载正常(meta 可能缺 faultTime,文件名合规退化)

## 风险与说明

- `docx` 包体积 ~200KB(gzip 后约 60KB),前端按需 import(reportDocx.js 内动态 `import('docx')`)避免增大首屏 chunk
- 故障时间含 `:`(如 `14:30`),macOS Finder 显示为 `:` 但底层是 `/`;统一把 `:` 也列入非法字符替换,保证跨平台
