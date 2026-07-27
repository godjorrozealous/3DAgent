<script setup>
import { ref, watch } from 'vue'
import { store } from '../store'
import { sendReportReview } from '../ws'

const opinionOpen = ref(false)
const instruction = ref('')

watch(() => store.reportReviewPending, (pending) => {
  if (pending) {
    opinionOpen.value = false
    instruction.value = ''
  }
})

function viewReport() {
  store.reportModal = {
    title: '复盘诊断报告',
    content: store.summaries.replay?.report || '',
  }
}

function approve() {
  sendReportReview(true)
  store.reportReviewPending = false
}

function submitRevision() {
  const text = instruction.value.trim()
  if (!text) return
  sendReportReview(false, text)
  store.reportReviewPending = false
}
</script>

<template>
  <div
    v-if="store.reportReviewPending"
    class="fixed inset-0 z-40 flex items-center justify-center pointer-events-none"
  >
    <div
      class="glass w-[400px] rounded-xl pointer-events-auto overflow-hidden"
      style="box-shadow: 0 0 40px rgba(16,185,129,.3)"
    >
      <!-- 标题栏 -->
      <div class="flex items-center gap-2 px-4 py-2.5 bg-emerald-500/10 border-b border-emerald-400/30">
        <span class="w-2 h-2 rounded-full bg-emerald-300 animate-pulse"></span>
        <span class="text-emerald-200 text-sm font-bold">复盘报告审核</span>
      </div>

      <!-- 内容 -->
      <div class="px-4 py-3 text-xs text-slate-200 leading-relaxed">
        复盘报告已生成，是否符合要求？
      </div>

      <!-- 意见输入区 -->
      <div v-if="opinionOpen" class="px-4 pb-3">
        <textarea
          v-model="instruction"
          rows="3"
          placeholder="请输入修改意见…"
          class="w-full bg-slate-900/80 border border-emerald-500/30 rounded px-3 py-1.5 text-xs text-emerald-100 outline-none focus:border-emerald-300 placeholder:text-slate-600 resize-none"
        ></textarea>
      </div>

      <!-- 按钮区 -->
      <div class="flex justify-end gap-2 px-4 py-2.5 border-t border-emerald-400/20 bg-slate-900/50">
        <button
          @click="viewReport"
          class="text-xs px-3 py-1.5 rounded bg-cyan-500/20 text-cyan-200 border border-cyan-400/40 hover:bg-cyan-400/30"
        >查看报告</button>
        <template v-if="!opinionOpen">
          <button
            @click="opinionOpen = true"
            class="text-xs px-3 py-1.5 rounded bg-amber-500/20 text-amber-200 border border-amber-400/40 hover:bg-amber-400/30"
          >有意见</button>
          <button
            @click="approve"
            class="text-xs font-bold px-3 py-1.5 rounded bg-emerald-500/25 text-emerald-200 border border-emerald-400/50 hover:bg-emerald-400/40"
          >符合要求</button>
        </template>
        <button
          v-else
          @click="submitRevision"
          :disabled="!instruction.trim()"
          class="text-xs font-bold px-3 py-1.5 rounded bg-amber-500/25 text-amber-200 border border-amber-400/50 hover:bg-amber-400/40 disabled:opacity-40 disabled:cursor-not-allowed"
        >提交修改</button>
      </div>
    </div>
  </div>
</template>
