<script setup>
import { ref, watch } from 'vue'
import { store } from '../store'
import { sendReportReview } from '../ws'

const opinionOpen = ref(false)
const instruction = ref('')
const opinionKind = ref('report')

watch(() => store.reportReviewPending, (pending) => {
  if (pending) {
    opinionOpen.value = false
    instruction.value = ''
    opinionKind.value = 'report'
  }
})

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

function approve() {
  sendReportReview(true)
  store.reportReviewPending = false
}

function submitRevision() {
  const text = instruction.value.trim()
  if (!text) return
  sendReportReview(false, text, opinionKind.value)
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
        <template v-if="store.reportReviewEmpty">⚠ 复盘报告内容为空，请提交「诊断流程问题」要求重新执行诊断。</template>
        <template v-else>复盘报告已生成，是否符合要求？</template>
      </div>

      <!-- 意见输入区 -->
      <div v-if="opinionOpen" class="px-4 pb-3">
        <div class="flex flex-col gap-1 mb-2 text-[11px]">
          <label class="flex items-center gap-1.5 text-slate-300 cursor-pointer">
            <input type="radio" value="report" v-model="opinionKind" class="accent-emerald-400" />
            报告表述问题（仅由报告智能体修改报告）
          </label>
          <label class="flex items-center gap-1.5 text-slate-300 cursor-pointer">
            <input type="radio" value="diagnosis" v-model="opinionKind" class="accent-amber-400" />
            诊断流程问题（司令收集意见后重新执行完整诊断）
          </label>
        </div>
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
