<script setup>
import { onMounted, ref } from 'vue'
import { store } from './store'
import { connect, onEvent } from './ws'
import { CommandRoom } from './three/CommandRoom'
import TopBar from './components/TopBar.vue'
import EventStream from './components/EventStream.vue'
import ReportViewer from './components/ReportViewer.vue'
import ChatModal from './components/ChatModal.vue'
import ReportModal from './components/ReportModal.vue'
import CompareModal from './components/CompareModal.vue'

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

onMounted(() => {
  const room = new CommandRoom(canvasHost.value, (agentId) => {
    store.chatTarget = agentId
  })
  onEvent((e) => {
    if (e.type === 'agent_status') room.setStatus(e.agent, e.status)
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
                @dblclick="store.chatTarget = a.id"
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
  </div>
</template>
