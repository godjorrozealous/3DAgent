<script setup>
import { computed, onMounted, ref } from 'vue'
import { store } from './store'
import { connect, onEvent } from './ws'
import { CommandRoom } from './three/CommandRoom'
import TopBar from './components/TopBar.vue'
import EventStream from './components/EventStream.vue'
import ReportViewer from './components/ReportViewer.vue'
import ChatModal from './components/ChatModal.vue'
import ReportModal from './components/ReportModal.vue'
import CompareModal from './components/CompareModal.vue'
import SavePromptModal from './components/SavePromptModal.vue'
import AgentSessionModal from './components/AgentSessionModal.vue'
import ReportReviewModal from './components/ReportReviewModal.vue'

const canvasHost = ref(null)
const leftOpen = ref(true)
const rightOpen = ref(true)

const STATUS_HINT = {
  idle: '待机',
  running: '诊断中',
  completed: '已完成',
  error: '告警',
}
const STATUS_CLASS = {
  idle: 'text-sky-400 border-sky-500/40',
  running: 'text-amber-300 border-amber-400/60 animate-pulse',
  completed: 'text-emerald-300 border-emerald-400/50',
  error: 'text-red-300 border-red-400/60 animate-pulse',
}

// 策略展示：工具名缩写与中文映射、默认权重基线
const TOOL_CN = { Lightning: '雷电', Icing: '覆冰', Wind: '风偏', Bird: '鸟害' }
const DEFAULT_WEIGHTS = { Lightning: 1.0, Icing: 0.9, Wind: 0.8, Bird: 0.6 }
const shortName = (t) => t.replace('DiagnosisTool', '')

const ALL_TOOLS = ['Lightning', 'Wind', 'Icing', 'Bird']
function buildStrategyText() {
  const excluded = new Set(store.excludedTools.map(shortName))
  const planned = new Set((store.plannedTools || []).map(shortName))
  const calls = ALL_TOOLS.filter(t => !excluded.has(t))
    .map(t => `${TOOL_CN[t]}×${store.weights[`${t}DiagnosisTool`] ?? DEFAULT_WEIGHTS[t]}`)
  const excl = [
    ...[...excluded].map(t => `${TOOL_CN[t] || t}(人工)`),
    ...ALL_TOOLS.filter(t => planned.size && !planned.has(t) && !excluded.has(t)).map(t => `${TOOL_CN[t]}(条件)`),
  ]
  return [
    `策略：${store.defaultSkill || '默认'}`,
    `调用：${calls.join('、') || '无'}`,
    `排除：${excl.join('、') || '无'}`,
  ].join('\n')
}

// HUD 调用标签：非排除工具全列（中文名×权重）
const callTags = computed(() => {
  const excluded = new Set(store.excludedTools.map(shortName))
  return ALL_TOOLS.filter((t) => !excluded.has(t))
    .map((t) => `${TOOL_CN[t]}×${store.weights[`${t}DiagnosisTool`] ?? DEFAULT_WEIGHTS[t]}`)
})
// HUD 排除标签：红=人工排除，灰=条件不满足（LLM 计划外）
const exclManual = computed(() => store.excludedTools.map(shortName))
const exclCond = computed(() => {
  const planned = new Set((store.plannedTools || []).map(shortName))
  const excluded = new Set(exclManual.value)
  if (!planned.size) return []
  return ALL_TOOLS.filter((t) => !planned.has(t) && !excluded.has(t))
})

// 诊断席位 -> PLD 工具名（复盘中双击席位打开 AgentSessionModal 私聊）
const TOOL_AGENTS = {
  lightning: 'LightningDiagnosisTool',
  wind: 'WindDiagnosisTool',
  icing: 'IcingDiagnosisTool',
  bird: 'BirdDamageDiagnosisTool',
}
function onAgentDblClick(agentId) {
  if (store.replayMode && TOOL_AGENTS[agentId]) {
    store.agentSession = { agent: agentId, tool: TOOL_AGENTS[agentId], confirm: false }
  } else {
    store.chatTarget = agentId
  }
}

onMounted(() => {
  const room = new CommandRoom(canvasHost.value, (agentId) => {
    onAgentDblClick(agentId)
  })
  onEvent((e) => {
    if (e.type === 'agent_status') room.setStatus(e.agent, e.status)
    if (e.type === 'session_snapshot' || e.type === 'skills') {
      room.updateStrategy(buildStrategyText())
    }
  })
  connect()
})
</script>

<template>
  <div class="relative w-full h-full">
    <!-- 3D WebGL 画布 -->
    <div ref="canvasHost" class="absolute inset-0"></div>

    <!-- HUD 覆盖层 -->
    <div class="absolute inset-0 pointer-events-none flex flex-col p-3 gap-2">
      <TopBar />

      <!-- 策略 HUD 信息卡：第一行=策略名+调用标签，第二行=排除标签（红=人工 / 灰=条件） -->
      <div class="self-start glass rounded-lg px-3 py-1.5 pointer-events-auto flex flex-col gap-1 text-[10px] max-w-[70%] overflow-hidden">
        <div class="flex items-center gap-1.5 flex-wrap">
          <span class="text-cyan-300 font-bold whitespace-nowrap">策略：{{ store.defaultSkill || '默认' }}</span>
          <span
            v-for="t in callTags" :key="'c-' + t"
            class="px-1.5 py-0.5 rounded bg-cyan-500/15 border border-cyan-400/40 text-cyan-200 whitespace-nowrap"
          >{{ t }}</span>
        </div>
        <div class="flex items-center gap-1.5 flex-wrap">
          <span class="text-slate-400 font-bold whitespace-nowrap">排除：</span>
          <template v-if="exclManual.length || exclCond.length">
            <span
              v-for="t in exclManual" :key="'x-' + t"
              class="px-1.5 py-0.5 rounded bg-red-500/15 border border-red-400/40 text-red-300 whitespace-nowrap"
            >{{ TOOL_CN[t] || t }}(人工)</span>
            <span
              v-for="t in exclCond" :key="'k-' + t"
              class="px-1.5 py-0.5 rounded bg-slate-500/15 border border-slate-400/40 text-slate-400 whitespace-nowrap"
            >{{ TOOL_CN[t] || t }}(条件)</span>
          </template>
          <span v-else class="text-slate-500 whitespace-nowrap">无</span>
        </div>
      </div>

      <div class="flex-1 flex gap-2 min-h-0">
        <!-- 左侧：事件流 + 状态矩阵（可折叠） -->
        <div v-if="leftOpen" class="w-[340px] shrink-0 flex flex-col gap-2 min-h-0 relative">
          <button
            @click="leftOpen = false"
            class="absolute -right-1 top-1/2 z-10 w-4 h-10 rounded-r bg-slate-800/80 border border-l-0 border-cyan-500/30 text-cyan-400 text-[10px] pointer-events-auto hover:bg-slate-700"
          >◀</button>
          <EventStream class="flex-1" />
          <div class="glass rounded-lg px-3 py-2 pointer-events-auto">
            <div class="text-cyan-300 text-[10px] font-bold tracking-widest mb-1.5">◢ 智能体状态矩阵</div>
            <div class="grid grid-cols-2 gap-1.5">
              <div
                v-for="a in store.agents" :key="a.id"
                class="flex items-center justify-between border rounded px-2 py-1 text-[10px] cursor-pointer hover:bg-cyan-500/10"
                :class="STATUS_CLASS[a.status] || STATUS_CLASS.idle"
                @dblclick="onAgentDblClick(a.id)"
              >
                <span>{{ a.name.replace('智能体', '') }}</span>
                <span>{{ STATUS_HINT[a.status] || '待机' }}</span>
              </div>
            </div>
            <div class="text-slate-500 text-[9px] mt-1.5">双击 3D 席位或状态卡片可直连该智能体</div>
          </div>
        </div>
        <button
          v-else
          @click="leftOpen = true"
          class="self-center w-5 h-16 rounded glass text-cyan-300 text-[10px] pointer-events-auto hover:bg-cyan-500/20 shrink-0"
          style="writing-mode: vertical-rl"
        >事件流 ▶</button>

        <div class="flex-1 min-w-0"><!-- 中央留给 3D 视野 --></div>

        <!-- 右侧：报告面板（可折叠） -->
        <button
          v-if="!rightOpen"
          @click="rightOpen = true"
          class="self-center w-5 h-16 rounded glass text-cyan-300 text-[10px] pointer-events-auto hover:bg-cyan-500/20 shrink-0"
          style="writing-mode: vertical-rl"
        >◀ 报告</button>
        <div v-else class="w-[460px] shrink-0 min-h-0 relative">
          <button
            @click="rightOpen = false"
            class="absolute -left-1 top-1/2 z-10 w-4 h-10 rounded-l bg-slate-800/80 border border-r-0 border-cyan-500/30 text-cyan-400 text-[10px] pointer-events-auto hover:bg-slate-700"
          >▶</button>
          <ReportViewer />
        </div>
      </div>
    </div>

    <!-- 双击智能体弹出的直聊终端 -->
    <ChatModal />
    <!-- 查看报告弹窗 -->
    <ReportModal />
    <!-- 实时/复盘比对弹窗 -->
    <CompareModal />
    <!-- 策略保存提醒弹窗 -->
    <SavePromptModal />
    <!-- 复盘合并大弹窗：子报告结果 + 私聊 + 快捷异议 -->
    <AgentSessionModal />
    <!-- 复盘报告审核弹窗 -->
    <ReportReviewModal />
  </div>
</template>
