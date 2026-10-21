<script setup>
import { store } from '../store'

function close() {
  store.historyModal = false
}

// 把答案文本按 URL 切分为片段：普通文本原样渲染，URL 变成可点链接（点开内置查看器）。
// URL 尾部紧跟的中英文标点（如「。」「，」「）」）不属于链接，剥掉避免点进去 404。
function linkify(text) {
  if (!text) return []
  const re = /https?:\/\/[!-~]+/g
  const parts = []
  let last = 0
  let m
  while ((m = re.exec(text))) {
    const url = m[0].replace(/[。，、；：？！）】》"',;.)\]]+$/, '')
    const tail = m[0].slice(url.length)
    if (m.index > last) parts.push({ text: text.slice(last, m.index) })
    if (url) parts.push({ text: url, url })
    if (tail) parts.push({ text: tail })
    last = m.index + m[0].length
  }
  if (last < text.length) parts.push({ text: text.slice(last) })
  return parts
}

function openLink(url) {
  store.linkViewer = { open: true, url }
}
</script>

<template>
  <div
    v-if="store.historyModal"
    class="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center pointer-events-auto"
    @click.self="close"
  >
    <div
      class="glass w-full max-w-2xl max-h-[70vh] rounded-xl flex flex-col overflow-hidden mx-4"
      style="box-shadow: 0 0 50px rgba(167,139,250,.25)"
    >
      <div class="flex items-center justify-between px-4 py-2.5 bg-violet-500/10 border-b border-violet-400/30 shrink-0">
        <div class="flex items-center gap-2">
          <span class="w-2 h-2 rounded-full bg-violet-300 animate-pulse"></span>
          <span class="text-violet-200 text-sm font-bold">历史关联(故障知识库)</span>
        </div>
        <button @click="close" class="text-slate-400 hover:text-red-300 text-lg leading-none px-1">×</button>
      </div>

      <div class="flex-1 overflow-y-auto px-5 py-4 text-[12px] text-slate-200 leading-relaxed">
        <div v-if="store.historyRelation.status === 'loading'" class="text-slate-500 italic text-center py-8">
          知识库查询中,请稍候……
        </div>
        <div v-else-if="store.historyRelation.status === 'error'" class="text-amber-300/90 text-center py-8">
          知识库服务未启动或查询失败。<br/>
          <span class="text-slate-500 text-[11px]">请确认 fault-knowledge-base 已启动(端口 8503);未启动不影响诊断功能。</span>
        </div>
        <div v-else-if="store.historyRelation.status === 'idle'" class="text-slate-500 italic text-center py-8">
          暂无关联数据(诊断启动后自动后台查询)
        </div>
        <template v-else>
          <div v-for="(s, i) in store.historyRelation.sections" :key="i" class="mb-4">
            <div class="text-violet-300 text-xs font-bold mb-1">{{ s.title }}</div>
            <div class="whitespace-pre-wrap text-slate-300"><template v-for="(p, j) in linkify(s.answer)" :key="j"><a
              v-if="p.url"
              href="#"
              @click.prevent="openLink(p.url)"
              class="text-violet-300 underline underline-offset-2 hover:text-violet-100 break-all"
              title="点击在弹窗中查看"
            >{{ p.text }}</a><span v-else>{{ p.text }}</span></template></div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
