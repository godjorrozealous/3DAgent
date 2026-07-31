<script setup>
import { store } from '../store'
import { startDiagnosis, openSaveNaming, replay, cancelQueued, setView } from '../ws'
</script>

<template>
  <header class="glass flex items-center gap-3 px-4 py-2 rounded-lg pointer-events-auto">
    <div class="flex items-center gap-2 shrink-0">
      <div class="w-2.5 h-2.5 rotate-45 bg-cyan-400 shadow-[0_0_10px_#22d3ee]"></div>
      <h1 class="text-cyan-300 font-bold tracking-widest neon-text text-sm whitespace-nowrap">
        输电线路智能诊断 · 全息指挥室
      </h1>
    </div>

    <input
      v-model="store.lineText"
      placeholder="输入线路跳闸信息，如：500kV雅湖线 #12杆塔 2026-07-31 14:23 跳闸"
      class="w-72 bg-slate-900/80 border border-cyan-500/40 text-cyan-100 text-xs rounded px-2 py-1.5 outline-none focus:border-cyan-300 placeholder:text-slate-600"
    />

    <button
      :disabled="!store.connected || !store.lineText.trim()"
      @click="startDiagnosis"
      class="text-xs font-bold px-4 py-1.5 rounded transition-all whitespace-nowrap"
      :class="store.running
        ? 'bg-amber-500/20 text-amber-300 border border-amber-400/50 hover:bg-amber-400/30'
        : 'bg-cyan-500/20 text-cyan-200 border border-cyan-400/60 hover:bg-cyan-400/30 hover:shadow-[0_0_16px_rgba(34,211,238,.5)]'"
      :title="store.running ? '诊断执行中，点击将新线路加入排队' : '开始实时诊断'"
    >
      {{ store.running ? '＋ 加入诊断队列' : '▶ 启动智能诊断' }}
    </button>

    <button
      :disabled="store.running || !store.connected || !store.sessionId"
      @click="openSaveNaming"
      class="text-xs font-bold px-3 py-1.5 rounded border border-fuchsia-400/50 text-fuchsia-200 bg-fuchsia-500/15 hover:bg-fuchsia-400/25 disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
      title="将当前会话的权重/排除/异议/自定义数据保存为完整策略技能"
    >
      ⬇ 保存干预策略
    </button>

    <button
      :disabled="store.running || !store.connected || !store.summaries.realtime"
      @click="replay"
      class="text-xs font-bold px-3 py-1.5 rounded border border-emerald-400/50 text-emerald-200 bg-emerald-500/15 hover:bg-emerald-400/25 disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
      title="实时诊断完成后即可复盘：逐项确认各智能体结果并审核报告"
    >
      ↻ 复盘重跑
    </button>

    <button
      @click="setView(store.view === 'room' ? 'history' : 'room')"
      class="text-xs font-bold px-3 py-1.5 rounded border border-sky-400/50 text-sky-200 bg-sky-500/15 hover:bg-sky-400/25 whitespace-nowrap"
      title="查看已完成的诊断结果集"
    >
      {{ store.view === 'room' ? '🗂 历史结果' : '🛖 指挥室' }}
    </button>

    <!-- 诊断队列 -->
    <div v-if="store.currentLine || store.diagQueue.length" class="flex items-center gap-1 text-[10px] shrink-0">
      <span
        v-if="store.currentLine"
        class="px-1.5 py-0.5 rounded bg-amber-500/15 border border-amber-400/40 text-amber-200 truncate max-w-[140px]"
        :title="store.currentLine"
      >诊断中:{{ store.currentLine }}</span>
      <span
        v-for="(q, i) in store.diagQueue" :key="i"
        class="px-1.5 py-0.5 rounded bg-slate-500/15 border border-slate-400/40 text-slate-300 truncate max-w-[120px]"
        :title="q.text"
      >
        等待{{ i + 1 }}:{{ q.text }}
        <button @click="cancelQueued(i)" class="text-red-300 hover:text-red-200 ml-0.5">✕</button>
      </span>
    </div>

    <div class="ml-auto flex items-center gap-2 text-xs shrink-0">
      <span
        class="w-2 h-2 rounded-full"
        :class="store.connected ? 'bg-emerald-400 shadow-[0_0_8px_#34d399]' : 'bg-red-400 animate-pulse'"
      ></span>
      <span :class="store.connected ? 'text-emerald-300' : 'text-red-300'">
        {{ store.connected ? '链路已建立' : '链路中断' }}
      </span>
    </div>
  </header>
</template>
