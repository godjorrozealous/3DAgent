<script setup>
import { computed } from 'vue'
import { store } from '../store'

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

// 轻量 Markdown 渲染（先转义再替换，避免 XSS）
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

const html = computed(() => renderMd(store.report))
</script>

<template>
  <aside class="glass rounded-lg flex flex-col pointer-events-auto h-full">
    <div class="px-3 py-2 border-b border-cyan-500/20 flex items-center justify-between">
      <span class="text-cyan-300 text-xs font-bold tracking-widest">诊断报告 ◣</span>
      <span v-if="store.report && !store.reportDone" class="text-amber-300 text-[10px] animate-pulse">生成中…</span>
      <span v-else-if="store.reportDone" class="text-emerald-300 text-[10px]">✓ 已签发</span>
    </div>
    <div class="flex-1 overflow-y-auto px-4 py-3 text-[12px] text-slate-200 leading-relaxed">
      <div v-if="!store.report" class="text-slate-500 italic h-full flex items-center justify-center text-center">
        司令员签发的诊断报告<br />将在此实时呈现
      </div>
      <div v-else class="md-body" v-html="html"></div>
    </div>
  </aside>
</template>
