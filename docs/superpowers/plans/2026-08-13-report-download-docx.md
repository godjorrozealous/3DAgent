# 报告下载为 Word 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 所有查看报告入口(实时/复盘摘要卡、历史结果、复盘审核)的 ReportModal 加「下载 Word」,前端 docx 库把 Markdown 报告生成 .docx 下载。

**Architecture:** 纯前端。新增 `reportDocx.js` 工具模块(Markdown→docx 段落→Blob→a[download]);ReportModal 标题栏加按钮;三处打开 reportModal 的入口补传 meta(线路名/故障时间)用于文件名。

**Tech Stack:** Vue 3 + Vite、docx(npm,浏览器端)

**Spec:** `docs/superpowers/specs/2026-08-13-report-download-docx-design.md`

## Global Constraints

- 提交一律 `git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit`(不改 git config);本计划只动外层仓 frontend
- 前端无测试框架:`npm run build` 通过即门槛(与前三轮同例)
- `docx` 必须动态 import(`await import('docx')`),不进入首屏 chunk
- 文件名非法字符 `[\\/:*?"<>|]` 替换为 `-`(含 `:`,跨平台);字段缺失略去该段
- backend / vendor 零改动

---

### Task 1: reportDocx.js 工具模块 + docx 依赖

**Files:**
- Create: `frontend/src/reportDocx.js`
- Modify: `frontend/package.json`(npm install 自动)
- Test: 无(构建验证)

**Interfaces:**
- Produces: `downloadReportDocx(title: string, content: string, meta?: { line?: string, faultTime?: string }): Promise<void>`;`docxFilename(title, meta): string`;Task 2 的 ReportModal 消费 `downloadReportDocx`

- [ ] **Step 1: 安装依赖**

```bash
cd frontend
npm install docx
```

- [ ] **Step 2: 实现 reportDocx.js**

新建 `frontend/src/reportDocx.js`:

```js
// 报告 Markdown → Word(.docx)下载。docx 库动态 import,不进首屏 chunk。

// 行内 **粗体** 解析为 TextRun 数组(其余文本普通 run)
function inlineRuns(docx, text) {
  const runs = []
  const re = /\*\*(.+?)\*\*/g
  let last = 0
  let m
  while ((m = re.exec(text))) {
    if (m.index > last) runs.push(new docx.TextRun(text.slice(last, m.index)))
    runs.push(new docx.TextRun({ text: m[1], bold: true }))
    last = m.index + m[0].length
  }
  if (last < text.length) runs.push(new docx.TextRun(text.slice(last)))
  return runs.length ? runs : [new docx.TextRun('')]
}

// Markdown → docx 段落数组(与 ReportModal renderMd 同级:
// #/##/### 标题、- 列表、**粗体**、--- 分隔;其余语法按纯文本段落)
function mdToChildren(docx, md) {
  const HEADING = [
    docx.HeadingLevel.HEADING_1,
    docx.HeadingLevel.HEADING_2,
    docx.HeadingLevel.HEADING_3,
  ]
  const children = []
  for (const line of String(md || '').split('\n')) {
    const t = line.trim()
    if (!t) continue
    if (t === '---') {
      children.push(new docx.Paragraph({}))
      continue
    }
    const h = t.match(/^(#{1,3})\s+(.*)$/)
    if (h) {
      children.push(new docx.Paragraph({
        heading: HEADING[h[1].length - 1],
        children: inlineRuns(docx, h[2]),
      }))
      continue
    }
    if (t.startsWith('- ')) {
      children.push(new docx.Paragraph({
        bullet: { level: 0 },
        children: inlineRuns(docx, t.slice(2)),
      }))
      continue
    }
    children.push(new docx.Paragraph({ children: inlineRuns(docx, t) }))
  }
  return children
}

const pad = (n) => String(n).padStart(2, '0')

// 文件名:{标题}_{线路名}_{故障时间}_{生成时间戳}.docx
// 非法字符 [\\/:*?"<>|] 替换为 -(含 :,跨平台);字段缺失略去该段
export function docxFilename(title, meta = {}) {
  const d = new Date()
  const ts = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}`
  const parts = [title, meta.line, meta.faultTime, ts]
    .filter((s) => s != null && String(s).trim() !== '')
    .map((s) => String(s).trim().replace(/[\\/:*?"<>|]/g, '-'))
  return `${parts.join('_')}.docx`
}

export async function downloadReportDocx(title, content, meta) {
  const docx = await import('docx')
  const doc = new docx.Document({ sections: [{ children: mdToChildren(docx, content) }] })
  const blob = await docx.Packer.toBlob(doc)
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = docxFilename(title, meta)
  a.click()
  URL.revokeObjectURL(url)
}
```

- [ ] **Step 3: 构建验证**

```bash
cd frontend
npm run build
```

预期:构建成功;dist 中出现 docx 的异步 chunk(与主 chunk 分离)。

- [ ] **Step 4: 提交(外层仓)**

```bash
cd "/Users/bei/DEVLOPE/3d agent"
git add frontend/package.json frontend/package-lock.json frontend/src/reportDocx.js
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat(frontend): reportDocx工具模块(Markdown→Word下载,docx动态import)"
```

---

### Task 2: ReportModal 下载按钮 + 三入口 meta

**Files:**
- Modify: `frontend/src/components/ReportModal.vue`(标题栏 44-50)
- Modify: `frontend/src/components/ReportViewer.vue`(openReport 35-40)
- Modify: `frontend/src/components/HistoryView.vue`(viewReport 69-71 + 两处按钮调用 105-115)
- Modify: `frontend/src/components/ReportReviewModal.vue`(viewReport 18-25)
- Modify: `frontend/src/store.js`(reportModal 注释 38)
- Test: 无(构建验证)

**Interfaces:**
- Consumes: Task 1 的 `downloadReportDocx(title, content, meta)`
- Produces: 无

- [ ] **Step 1: ReportModal 下载按钮**

`frontend/src/components/ReportModal.vue`:

① script 顶部 import 后加:

```js
import { downloadReportDocx } from '../reportDocx'

function download() {
  const m = store.reportModal
  if (m?.content) downloadReportDocx(m.title, m.content, m.meta)
}
```

② 标题栏(44-50)关闭 × 按钮左侧加:

```html
        <button
          :disabled="!store.reportModal.content"
          @click="download"
          class="text-xs px-2.5 py-1 rounded border border-cyan-400/50 text-cyan-200 bg-cyan-500/15 hover:bg-cyan-400/25 disabled:opacity-40 disabled:cursor-not-allowed mr-2"
        >下载 Word</button>
```

- [ ] **Step 2: store.js 注释更新**

`frontend/src/store.js:38` 改为:

```js
  reportModal: null,     // null | { title, content, meta?: { line, faultTime } }
```

- [ ] **Step 3: SummaryCard openReport 补 meta**

`frontend/src/components/ReportViewer.vue` openReport(35-40)改为:

```js
    function openReport() {
      store.reportModal = {
        title: `${props.kind === 'realtime' ? '实时' : '复盘'}诊断报告`,
        content: props.data?.report || '',
        meta: {
          line: props.data?.summary?.line_name,
          faultTime: props.data?.summary?.fault_time,
        },
      }
    }
```

- [ ] **Step 4: HistoryView viewReport 补 meta**

`frontend/src/components/HistoryView.vue`:

① viewReport(69-71)改为:

```js
function viewReport(title, content, summary) {
  store.reportModal = {
    title,
    content: content || '（空）',
    meta: { line: store.recordDetail?.line, faultTime: summary?.fault_time },
  }
}
```

② 实时报告按钮(105-109)@click 改为:

```html
              @click="viewReport('实时诊断报告', store.recordDetail.realtime.report, store.recordDetail.realtime.summary)"
```

③ 复盘报告按钮(111-114)@click 改为:

```html
              @click="viewReport('复盘报告' + (store.recordDetail.replays.length > 1 ? ' ' + (i + 1) : ''), rp.report, rp.summary)"
```

- [ ] **Step 5: ReportReviewModal viewReport 补 meta**

`frontend/src/components/ReportReviewModal.vue` viewReport(18-25)改为:

```js
function viewReport() {
  // report_summary 在复盘完全结束(_finish_run)后才广播，审核提问时还没有；
  // 此时完整报告已在 store.report（诊断 complete 事件推送），优先回退到它
  store.reportModal = {
    title: '复盘诊断报告',
    content: store.summaries.replay?.report || store.report || '',
    meta: {
      line: store.summaries.replay?.summary?.line_name || store.currentLine,
      faultTime: store.summaries.replay?.summary?.fault_time,
    },
  }
}
```

- [ ] **Step 6: 构建验证**

```bash
cd frontend
npm run build
```

预期:构建成功无报错。

- [ ] **Step 7: 提交(外层仓)**

```bash
cd "/Users/bei/DEVLOPE/3d agent"
git add frontend/src/components/ReportModal.vue frontend/src/components/ReportViewer.vue frontend/src/components/HistoryView.vue frontend/src/components/ReportReviewModal.vue frontend/src/store.js
git -c user.name="北" -c user.email="bei@beideMac-mini.local" commit -m "feat(frontend): ReportModal下载Word按钮+三入口补meta(线路名/故障时间)"
```

---

### Task 3: 全量回归 + 实测核对清单

**Files:** 无(纯验证)

**Interfaces:**
- Consumes: Task 1-2 完成
- Produces: 无

- [ ] **Step 1: 前端构建**

```bash
cd frontend
npm run build 2>&1 | tail -3
```

预期:成功。

- [ ] **Step 2: backend / vendor 回归(零改动确认)**

```bash
cd backend && .venv/bin/python -m pytest tests/ -q
cd vendor/diagnosis-agent && .venv/bin/python -m pytest tests/ -q --ignore=tests/integration/test_diagnose_flow.py
```

预期:85 / 372 passed(本计划未动两端,确认无误伤)。

- [ ] **Step 3: 实测核对(记录交用户)**

1. 实时摘要卡「查看报告」→「下载 Word」→ Word 打开:标题层级/列表/粗体正确;文件名含线路名+故障时间+时间戳
2. 复盘摘要卡同上
3. 历史结果页「实时诊断报告」「复盘报告 N」→ 下载,文件名含该记录线路名
4. 复盘审核期「查看报告」→ 下载正常(meta 缺省时文件名退化为 标题+时间戳)
5. 报告为空时按钮禁用

---

## Self-Review 记录

- Spec 覆盖:§1 reportDocx+文件名→Task 1;§2 转换规则→Task 1 Step 2(逐条对应 renderMd 能力);§3 meta 三入口→Task 2 Step 3-5;§4 按钮→Task 2 Step 1;测试→Task 3;「不做的事」→无任务,符合
- 占位符:全部代码完整给出;docx API(Document/Packer/Paragraph/TextRun/HeadingLevel/bullet)为库稳定公开 API
- 类型一致:`downloadReportDocx(title, content, meta?)` Task 1 产出与 Task 2 消费一致;`meta = { line, faultTime }` 三入口同构;records.py:52-57 确认 realtime/replays[i] 均存 summary(含 fault_time)
- 动态 import:mdToChildren/inlineRuns 以 docx 模块为参,避免顶层静态 import 进首屏 chunk;docxFilename 无依赖可静态导出
