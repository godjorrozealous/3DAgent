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
