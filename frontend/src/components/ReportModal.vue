<script setup>
import { computed, ref, watch } from 'vue'
import { store } from '../store'
import { downloadReportDocx } from '../reportDocx'

// live 模式:报告流式生成中打开,直接渲染 store.report 增量文本,完成后转 md
const live = computed(() => !!store.reportModal?.live)
const streaming = computed(() => live.value && !store.reportDone)
const content = computed(() =>
  live.value ? store.report : (store.reportModal?.content || ''))

function download() {
  const m = store.reportModal
  if (content.value) downloadReportDocx(m.title, content.value, m.meta).catch((e) => console.error('报告下载失败', e))
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

// 轻量 Markdown 渲染（先转义再替换，避免 XSS；迁移自旧 ReportViewer）
function renderMd(md) {
  let h = escapeHtml(md)
  h = h.replace(/^### (.*)$/gm, '<h3>$1</h3>')
  h = h.replace(/^## (.*)$/gm, '<h2>$1</h2>')
  h = h.replace(/^# (.*)$/gm, '<h1>$1</h1>')
  h = h.replace(/^---$/gm, '<hr/>')
  h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  // 列表
  h = h.replace(/(?:^|\n)((?:- .*(?:\n|$))+)/g, (m, block) => {
    const items = block.trim().split('\n').map((l) => `<li>${l.replace(/^- /, '')}</li>`).join('')
    return `\n<ul>${items}</ul>`
  })
  h = h.replace(/\n{2,}/g, '<br/><br/>').replace(/\n/g, '<br/>')
  return h
}

const html = computed(() => renderMd(content.value))

// 流式期间自动滚动到底部
const bodyEl = ref(null)
watch(() => store.report, () => {
  const el = bodyEl.value
  if (el && streaming.value) el.scrollTop = el.scrollHeight
})

function close() {
  store.reportModal = null
}
</script>

<template>
  <div
    v-if="store.reportModal"
    class="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center pointer-events-auto"
    @click.self="close"
  >
    <div
      class="glass w-full max-w-3xl max-h-[80vh] rounded-xl flex flex-col overflow-hidden mx-4"
      style="box-shadow: 0 0 50px rgba(34,211,238,.25)"
    >
      <!-- 标题栏 -->
      <div class="flex items-center justify-between px-4 py-2.5 bg-cyan-500/10 border-b border-cyan-400/30 shrink-0">
        <div class="flex items-center gap-2">
          <span class="w-2 h-2 rounded-full bg-cyan-300 animate-pulse"></span>
          <span class="text-cyan-200 text-sm font-bold">{{ store.reportModal.title }}</span>
          <span v-if="streaming" class="text-cyan-400/80 text-[10px] font-bold tracking-widest">正在生成…</span>
        </div>
        <div class="flex items-center">
          <button
            :disabled="!content || streaming"
            @click="download"
            class="text-xs px-2.5 py-1 rounded border border-cyan-400/50 text-cyan-200 bg-cyan-500/15 hover:bg-cyan-400/25 disabled:opacity-40 disabled:cursor-not-allowed mr-2"
          >下载 Word</button>
          <button @click="close" class="text-slate-400 hover:text-red-300 text-lg leading-none px-1">×</button>
        </div>
      </div>

      <!-- 内容区 -->
      <div ref="bodyEl" class="flex-1 overflow-y-auto px-5 py-4 text-[12px] text-slate-200 leading-relaxed">
        <div v-if="streaming" class="whitespace-pre-wrap">{{ content || '等待报告流式输出……' }}</div>
        <div v-else-if="!content" class="text-slate-500 italic text-center py-8">报告内容为空</div>
        <div v-else class="md-body" v-html="html"></div>
      </div>
    </div>
  </div>
</template>
