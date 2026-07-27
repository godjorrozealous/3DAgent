<script setup>
import { computed, ref, watch } from 'vue'
import { store } from '../store'
import { sendToolConfirm } from '../ws'

const expanded = ref(false)
const decision = ref('')
const weightValue = ref(1.0)
const overrideValue = ref('')

const head = computed(() => (store.confirmQueue.length ? store.confirmQueue[0] : null))
const agentName = computed(() => {
  const e = head.value
  if (!e) return ''
  return store.agents[e.agent]?.name || e.tool.replace('DiagnosisTool', '')
})
const toolShort = computed(() => (head.value ? head.value.tool.replace('DiagnosisTool', '') : ''))

// 队列头变化时重置展开状态
watch(head, () => {
  expanded.value = false
  decision.value = ''
  weightValue.value = 1.0
  overrideValue.value = ''
})

const confirmDisabled = computed(() => {
  if (!decision.value) return true
  if (decision.value === 'weight') return weightValue.value === null || weightValue.value === ''
  if (decision.value === 'override') return !overrideValue.value.trim()
  return false
})

const OPTIONS = [
  { key: 'recheck', label: '重新检查' },
  { key: 'exclude', label: '数据不对去掉' },
  { key: 'weight', label: '调整权重' },
  { key: 'override', label: '手动改值' },
]

function agree() {
  const e = head.value
  if (!e) return
  sendToolConfirm(e.tool, 'ok')
  store.confirmQueue.shift()
}

function submitObjection() {
  const e = head.value
  if (!e || confirmDisabled.value) return
  let value
  if (decision.value === 'weight') value = Number(weightValue.value)
  else if (decision.value === 'override') value = overrideValue.value.trim()
  sendToolConfirm(e.tool, decision.value, value)
  store.confirmQueue.shift()
}
</script>

<template>
  <div
    v-if="head"
    class="fixed inset-0 z-40 flex items-center justify-center pointer-events-none"
  >
    <div
      class="glass w-[400px] rounded-xl pointer-events-auto overflow-hidden"
      style="box-shadow: 0 0 40px rgba(34,211,238,.3)"
    >
      <!-- 标题栏 -->
      <div class="flex items-center justify-between px-4 py-2.5 bg-cyan-500/10 border-b border-cyan-400/30">
        <div class="flex items-center gap-2">
          <span class="w-2 h-2 rounded-full bg-cyan-300 animate-pulse"></span>
          <span class="text-cyan-200 text-sm font-bold">诊断结论确认</span>
        </div>
        <span class="text-[10px] text-slate-500">队列 {{ store.confirmQueue.length }}</span>
      </div>

      <!-- 内容 -->
      <div class="px-4 py-3 space-y-2 text-xs">
        <div class="flex items-center gap-2">
          <span class="text-slate-400 shrink-0">智能体</span>
          <span class="text-cyan-200 font-bold">{{ agentName }}</span>
          <span class="text-slate-500">·</span>
          <span class="text-slate-300">{{ toolShort }}</span>
        </div>
        <div class="flex items-center gap-2">
          <span class="text-slate-400 shrink-0">倾向</span>
          <span class="text-amber-200 font-bold">{{ head.fault_type }}</span>
          <span class="text-slate-500">·</span>
          <span class="text-slate-400">置信度</span>
          <span class="text-emerald-300 font-bold">{{ head.confidence }}</span>
        </div>
        <div class="rounded-lg border border-slate-600/40 bg-slate-800/50 px-3 py-2 text-[11px] text-slate-300 leading-relaxed">
          <div class="text-slate-500 text-[10px] mb-1">证据</div>
          {{ head.evidence }}
        </div>
        <div v-if="head.override" class="text-[11px] text-amber-300">
          已改值：{{ head.override }}
        </div>
      </div>

      <!-- 异议展开区 -->
      <div v-if="expanded" class="px-4 pb-3 space-y-1.5">
        <div
          v-for="opt in OPTIONS"
          :key="opt.key"
          class="flex items-center gap-2 rounded-lg border px-3 py-1.5 cursor-pointer text-[11px]"
          :class="decision === opt.key
            ? 'border-amber-400/60 bg-amber-500/15 text-amber-200'
            : 'border-slate-600/40 bg-slate-800/50 text-slate-300 hover:border-slate-500/60'"
          @click="decision = opt.key"
        >
          <span
            class="w-2.5 h-2.5 rounded-full border shrink-0"
            :class="decision === opt.key ? 'bg-amber-300 border-amber-300' : 'border-slate-500'"
          ></span>
          <span>{{ opt.label }}</span>
          <input
            v-if="opt.key === 'weight' && decision === 'weight'"
            v-model.number="weightValue"
            type="number"
            step="0.1"
            class="ml-auto w-20 bg-slate-900/80 border border-amber-500/30 rounded px-2 py-0.5 text-xs text-amber-100 outline-none focus:border-amber-300"
            @click.stop
          />
          <input
            v-if="opt.key === 'override' && decision === 'override'"
            v-model="overrideValue"
            type="text"
            placeholder="输入修改值…"
            class="ml-auto flex-1 max-w-[180px] bg-slate-900/80 border border-amber-500/30 rounded px-2 py-0.5 text-xs text-amber-100 outline-none focus:border-amber-300 placeholder:text-slate-600"
            @click.stop
          />
        </div>
      </div>

      <!-- 按钮区 -->
      <div class="flex justify-end gap-2 px-4 py-2.5 border-t border-cyan-400/20 bg-slate-900/50">
        <button
          @click="expanded = !expanded"
          class="text-xs px-3 py-1.5 rounded border"
          :class="expanded
            ? 'bg-amber-500/20 text-amber-200 border-amber-400/50 hover:bg-amber-400/30'
            : 'bg-slate-700/40 text-slate-300 border-slate-500/40 hover:bg-slate-600/40'"
        >有异议▾</button>
        <button
          v-if="expanded"
          @click="submitObjection"
          :disabled="confirmDisabled"
          class="text-xs font-bold px-3 py-1.5 rounded bg-amber-500/25 text-amber-200 border border-amber-400/50 hover:bg-amber-400/40 disabled:opacity-40 disabled:cursor-not-allowed"
        >确认异议</button>
        <button
          v-else
          @click="agree"
          class="text-xs font-bold px-3 py-1.5 rounded bg-emerald-500/25 text-emerald-200 border border-emerald-400/50 hover:bg-emerald-400/40"
        >无异议</button>
      </div>
    </div>
  </div>
</template>
