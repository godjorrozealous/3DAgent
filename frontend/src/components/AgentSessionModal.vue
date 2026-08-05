<script setup>
import { computed, ref, watch, nextTick } from 'vue'
import { store } from '../store'
import { sendChat, sendToolConfirm, echoChat } from '../ws'

// PLD 工具名 -> 智能体席位 id（与后端 agent_manager.TOOL_TO_AGENT 一致）
const TOOL_TO_AGENT = {
  LightningDiagnosisTool: 'lightning',
  WindDiagnosisTool: 'wind',
  IcingDiagnosisTool: 'icing',
  BirdDamageDiagnosisTool: 'bird',
}

const session = computed(() => store.agentSession)
const isConfirm = computed(() => !!session.value?.confirm)
const agent = computed(() => {
  const s = session.value
  if (!s) return null
  return s.agent || TOOL_TO_AGENT[s.tool] || null
})
const agentName = computed(() => {
  const s = session.value
  if (!s) return ''
  return (agent.value && store.agents[agent.value]?.name) || (s.tool || '').replace('DiagnosisTool', '')
})
const toolShort = computed(() => (session.value?.tool || '').replace('DiagnosisTool', ''))

// ---- 结果区 ----
const resultRows = computed(() => {
  const sd = session.value?.structured_data
  if (!sd || typeof sd !== 'object') return []
  return Object.entries(sd).map(([key, val]) => ({
    key,
    items: Array.isArray(val) ? val.map((v) => fmtVal(v)) : null,
    value: Array.isArray(val) ? null : fmtVal(val),
  }))
})
function fmtVal(v) {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'object') return JSON.stringify(v, null, 0)
  return String(v)
}
const rawText = computed(() => session.value?.raw_text || '')
const hasResult = computed(() => resultRows.value.length > 0 || !!rawText.value)

// ---- 对话区 ----
const input = ref('')
const listEl = ref(null)
const messages = computed(() => (agent.value ? store.chatMessages[agent.value] || [] : []))

watch(messages, async () => {
  await nextTick()
  if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
}, { deep: true })

function submitChat() {
  const text = input.value.trim()
  if (!text || !agent.value) return
  sendChat(agent.value, text)
  input.value = ''
}

// ---- 操作区（仅 confirm 模式）----
const weightValue = ref(1.0)
const overrideValue = ref('')
const timeStart = ref('')
const timeEnd = ref('')

// 会话切换时重置输入
watch(session, () => {
  input.value = ''
  weightValue.value = 1.0
  overrideValue.value = ''
  timeStart.value = ''
  timeEnd.value = ''
})

const canWeight = computed(() => weightValue.value !== null && weightValue.value !== '' && !Number.isNaN(Number(weightValue.value)))
const canOverride = computed(() => !!overrideValue.value.trim())

function advance() {
  store.confirmQueue.shift()
  store.agentSession = store.confirmQueue.length
    ? { ...store.confirmQueue[0], confirm: true }
    : null
}

function submit(decision) {
  const s = session.value
  if (!s) return
  let value
  if (decision === 'recheck') {
    if (timeStart.value.trim() && timeEnd.value.trim()) {
      decision = 'time_range'
      value = `${timeStart.value.trim()}~${timeEnd.value.trim()}`
    }
  } else if (decision === 'weight') {
    if (!canWeight.value) return
    value = Number(weightValue.value)
  } else if (decision === 'override') {
    if (!canOverride.value) return
    value = overrideValue.value.trim()
  }
  sendToolConfirm(s.tool, decision, value)
  // spec §6：快捷按钮在对话区生成对应指令消息（仅本地回显 echoChat，不转发 PLD；
  // 决策已由 tool_confirm_response 携带，转发会被误判新诊断并劫持活跃会话）
  const a = agent.value
  if (a) {
    const text =
      decision === 'recheck' ? '请重新检查'
      : decision === 'time_range' ? `请重新检查，查询时间段 ${value}`
      : decision === 'exclude' ? '该数据不对，去掉'
      : decision === 'weight' ? `调整权重为 ${value}`
      : decision === 'override' ? `手填数据：${value}`
      : '无异议'
    echoChat(a, text)
  }
  advance()
}

function close() {
  if (isConfirm.value) return
  store.agentSession = null
  // 私聊关闭后提升确认队列队首，避免排队确认饿死
  if (store.confirmQueue.length) store.agentSession = { ...store.confirmQueue[0], confirm: true }
}
</script>

<template>
  <div
    v-if="session"
    class="fixed inset-0 z-40 flex items-center justify-center pointer-events-none"
  >
    <div
      class="glass w-[720px] max-h-[85vh] rounded-xl pointer-events-auto flex flex-col overflow-hidden"
      style="box-shadow: 0 0 40px rgba(34,211,238,.3)"
    >
      <!-- 标题栏 -->
      <div class="flex items-center justify-between px-4 py-2.5 bg-cyan-500/10 border-b border-cyan-400/30 shrink-0">
        <div class="flex items-center gap-2 min-w-0">
          <span class="w-2 h-2 rounded-full bg-cyan-300 animate-pulse shrink-0"></span>
          <span class="text-cyan-200 text-sm font-bold whitespace-nowrap">{{ agentName }}</span>
          <span class="text-slate-500">·</span>
          <span class="text-slate-300 text-xs whitespace-nowrap">{{ toolShort }}</span>
          <template v-if="session.fault_type">
            <span class="text-slate-500">·</span>
            <span class="text-slate-400 text-xs whitespace-nowrap">倾向</span>
            <span class="text-amber-200 text-xs font-bold whitespace-nowrap">{{ session.fault_type }}</span>
          </template>
          <template v-if="session.confidence !== undefined && session.confidence !== null">
            <span class="text-slate-500">·</span>
            <span class="text-slate-400 text-xs whitespace-nowrap">置信度</span>
            <span class="text-emerald-300 text-xs font-bold whitespace-nowrap">{{ session.confidence }}</span>
          </template>
          <span
            v-if="isConfirm"
            class="shrink-0 text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-200 border border-amber-400/40 whitespace-nowrap"
          >待确认 · 队列 {{ store.confirmQueue.length }}</span>
          <span
            v-else
            class="shrink-0 text-[10px] px-1.5 py-0.5 rounded bg-cyan-500/15 text-cyan-300 border border-cyan-400/40 whitespace-nowrap"
          >私聊</span>
        </div>
        <button
          v-if="!isConfirm"
          @click="close"
          class="text-slate-400 hover:text-red-300 text-lg leading-none px-1 shrink-0"
        >×</button>
      </div>

      <!-- 空结果标记 -->
      <div
        v-if="session.empty"
        class="px-4 py-2 text-[11px] text-amber-300 bg-amber-500/10 border-b border-amber-400/30 shrink-0"
      >⚠ 该智能体本轮未返回有效结果，可点击「重新检查」要求重跑该工具</div>

      <!-- 结果区 -->
      <div v-if="hasResult" class="max-h-56 overflow-y-auto px-4 py-3 border-b border-cyan-400/20 shrink-0">
        <div class="text-slate-500 text-[10px] mb-1.5">子报告结构化结果</div>
        <div class="space-y-1 text-[11px]">
          <div v-for="row in resultRows" :key="row.key" class="flex gap-2 items-start">
            <span class="text-slate-400 shrink-0 w-28 truncate" :title="row.key">{{ row.key }}</span>
            <div v-if="row.items" class="flex-1 min-w-0 space-y-0.5">
              <div
                v-for="(item, i) in row.items" :key="i"
                class="text-slate-200 rounded border border-slate-600/40 bg-slate-800/50 px-2 py-0.5 leading-relaxed"
              >{{ item }}</div>
            </div>
            <span v-else class="flex-1 min-w-0 text-slate-200 break-all">{{ row.value }}</span>
          </div>
        </div>
        <div v-if="rawText" class="mt-2">
          <div class="text-slate-500 text-[10px] mb-1">原始子报告</div>
          <div class="rounded-lg border border-slate-600/40 bg-slate-800/50 px-3 py-2 text-[11px] text-slate-300 leading-relaxed whitespace-pre-wrap">{{ rawText }}</div>
        </div>
        <div v-if="session.override" class="mt-1.5 text-[11px] text-amber-300">已改值：{{ session.override }}</div>
      </div>

      <!-- 对话区 -->
      <div ref="listEl" class="flex-1 min-h-32 overflow-y-auto px-4 py-3 space-y-2.5 font-mono text-[12px]">
        <div class="text-slate-500 italic text-[11px]">
          与「{{ agentName }}」直连会话，可追问证据、要求重查指定时间段数据
        </div>
        <div v-for="(m, i) in messages" :key="i" class="flex" :class="m.from === 'user' ? 'justify-end' : 'justify-start'">
          <div
            class="max-w-[85%] rounded-lg px-3 py-1.5"
            :class="m.from === 'user'
              ? 'bg-cyan-500/20 text-cyan-100 border border-cyan-400/40'
              : 'bg-slate-800/70 text-slate-200 border border-slate-600/50'"
          >
            <div class="text-[10px] opacity-60 mb-0.5">{{ m.from === 'user' ? '指挥员' : agentName }} · {{ m.time }}</div>
            {{ m.message }}
          </div>
        </div>
      </div>

      <!-- 对话输入区 -->
      <div class="flex gap-2 px-3 py-2 border-t border-cyan-400/20 bg-slate-900/50 shrink-0">
        <input
          v-model="input"
          @keyup.enter="submitChat"
          placeholder="追问该智能体，回车发送…"
          class="flex-1 bg-slate-900/80 border border-cyan-500/30 rounded px-3 py-1.5 text-xs text-cyan-100 outline-none focus:border-cyan-300 placeholder:text-slate-600"
        />
        <button
          @click="submitChat"
          class="text-xs font-bold px-3.5 rounded bg-cyan-500/25 text-cyan-200 border border-cyan-400/50 hover:bg-cyan-400/40"
        >发送</button>
      </div>

      <!-- 操作区（仅确认模式） -->
      <div v-if="isConfirm" class="border-t border-amber-400/20 bg-slate-900/60 px-3 py-2.5 space-y-2 shrink-0">
        <div class="flex flex-wrap items-center gap-2">
          <button
            @click="submit('recheck')"
            class="text-xs px-3 py-1.5 rounded bg-slate-700/40 text-slate-200 border border-slate-500/40 hover:bg-slate-600/40"
          >重新检查</button>
          <button
            @click="submit('exclude')"
            class="text-xs px-3 py-1.5 rounded bg-red-500/15 text-red-300 border border-red-400/40 hover:bg-red-400/25"
          >数据不对去掉</button>
          <button
            @click="submit('weight')"
            :disabled="!canWeight"
            class="text-xs px-3 py-1.5 rounded bg-amber-500/20 text-amber-200 border border-amber-400/50 hover:bg-amber-400/30 disabled:opacity-40 disabled:cursor-not-allowed"
          >调整权重</button>
          <input
            v-model.number="weightValue"
            type="number"
            step="0.1"
            class="w-20 bg-slate-900/80 border border-amber-500/30 rounded px-2 py-1 text-xs text-amber-100 outline-none focus:border-amber-300"
          />
          <button
            @click="submit('override')"
            :disabled="!canOverride"
            class="text-xs px-3 py-1.5 rounded bg-amber-500/20 text-amber-200 border border-amber-400/50 hover:bg-amber-400/30 disabled:opacity-40 disabled:cursor-not-allowed"
          >手填数据</button>
          <input
            v-model="overrideValue"
            type="text"
            placeholder="输入修改值…"
            class="flex-1 min-w-[120px] bg-slate-900/80 border border-amber-500/30 rounded px-2 py-1 text-xs text-amber-100 outline-none focus:border-amber-300 placeholder:text-slate-600"
          />
          <button
            @click="submit('ok')"
            class="text-xs font-bold px-3 py-1.5 rounded bg-emerald-500/25 text-emerald-200 border border-emerald-400/50 hover:bg-emerald-400/40"
          >无异议</button>
        </div>
        <div class="flex items-center gap-2 text-[10px] text-slate-500">
          <span class="whitespace-nowrap">重查时间段（均填则按时间段重查）：</span>
          <input
            v-model="timeStart"
            type="text"
            placeholder="起 19:40"
            class="w-24 bg-slate-900/80 border border-slate-500/40 rounded px-2 py-1 text-xs text-slate-200 outline-none focus:border-cyan-300 placeholder:text-slate-600"
          />
          <span>~</span>
          <input
            v-model="timeEnd"
            type="text"
            placeholder="止 19:50"
            class="w-24 bg-slate-900/80 border border-slate-500/40 rounded px-2 py-1 text-xs text-slate-200 outline-none focus:border-cyan-300 placeholder:text-slate-600"
          />
        </div>
      </div>
    </div>
  </div>
</template>
