<script setup>
// 链接查看器：历史关联(知识库)正文里的来源文件超链接，点击后内嵌展示（通常是 PDF）。
// 知识库文件服务器返回 application/pdf 且无 X-Frame-Options，浏览器可在 iframe 中原生渲染。
import { computed, onMounted, onUnmounted } from 'vue'
import { store } from '../store'

// 经后端预览代理统一展示：PDF 透传；Word/WPS 由后端转 PDF；
// 无法预览时代理返回带下载出口的提示页（不再静默触发浏览器下载）。
const previewSrc = computed(
  () => `/api/file-preview?url=${encodeURIComponent(store.linkViewer.url)}`
)

function close() {
  store.linkViewer.open = false
}

function openExternal() {
  window.open(store.linkViewer.url, '_blank')
}

function onKey(e) {
  if (e.key === 'Escape') close()
}

onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div
    v-if="store.linkViewer.open"
    class="fixed inset-0 z-[60] bg-black/70 backdrop-blur-sm flex items-center justify-center pointer-events-auto"
    @click.self="close"
  >
    <div
      class="glass w-[92vw] max-w-5xl h-[85vh] rounded-xl flex flex-col overflow-hidden mx-4"
      style="box-shadow: 0 0 50px rgba(167,139,250,.25)"
    >
      <div class="flex items-center justify-between gap-3 px-4 py-2.5 bg-violet-500/10 border-b border-violet-400/30 shrink-0">
        <div class="flex items-center gap-2 min-w-0">
          <span class="w-2 h-2 rounded-full bg-violet-300 animate-pulse shrink-0"></span>
          <span class="text-violet-200 text-sm font-bold shrink-0">来源文件</span>
          <span class="text-slate-500 text-[11px] truncate">{{ store.linkViewer.url }}</span>
        </div>
        <div class="flex items-center gap-2 shrink-0">
          <button
            @click="openExternal"
            class="text-slate-400 hover:text-violet-200 text-xs border border-slate-600/60 hover:border-violet-400/50 rounded px-2 py-0.5"
            title="iframe 无法显示时，用浏览器新标签页打开"
          >新窗口打开</button>
          <button @click="close" class="text-slate-400 hover:text-red-300 text-lg leading-none px-1">×</button>
        </div>
      </div>
      <iframe :src="previewSrc" class="flex-1 w-full bg-white" title="来源文件预览"></iframe>
    </div>
  </div>
</template>
