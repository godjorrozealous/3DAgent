<script setup>
import { store, LINES } from '../store'
import { startDiagnosis, saveStrategy, replay } from '../ws'
</script>

<template>
  <header class="glass flex items-center gap-3 px-4 py-2 rounded-lg pointer-events-auto">
    <div class="flex items-center gap-2 shrink-0">
      <div class="w-2.5 h-2.5 rotate-45 bg-cyan-400 shadow-[0_0_10px_#22d3ee]"></div>
      <h1 class="text-cyan-300 font-bold tracking-widest neon-text text-sm whitespace-nowrap">
        输电线路智能诊断 · 全息指挥室
      </h1>
    </div>

    <select
      v-model="store.selectedLine"
      class="bg-slate-900/80 border border-cyan-500/40 text-cyan-100 text-xs rounded px-2 py-1.5 outline-none focus:border-cyan-300"
    >
      <option v-for="(l, i) in LINES" :key="i" :value="i">{{ l.line }} · {{ l.tower }}</option>
    </select>

    <button
      :disabled="store.running || !store.connected"
      @click="startDiagnosis"
      class="text-xs font-bold px-4 py-1.5 rounded transition-all whitespace-nowrap"
      :class="store.running
        ? 'bg-amber-500/20 text-amber-300 border border-amber-400/50 cursor-wait'
        : 'bg-cyan-500/20 text-cyan-200 border border-cyan-400/60 hover:bg-cyan-400/30 hover:shadow-[0_0_16px_rgba(34,211,238,.5)]'"
    >
      {{ store.running ? '诊断执行中…' : '▶ 启动智能诊断' }}
    </button>

    <button
      :disabled="store.running || !store.connected || !store.sessionId"
      @click="saveStrategy"
      class="text-xs font-bold px-3 py-1.5 rounded border border-fuchsia-400/50 text-fuchsia-200 bg-fuchsia-500/15 hover:bg-fuchsia-400/25 disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
      title="将当前会话的工具权重与排除策略保存为技能"
    >
      ⬇ 保存干预策略
    </button>

    <button
      :disabled="store.running || !store.connected || !store.strategies.length"
      @click="replay"
      class="text-xs font-bold px-3 py-1.5 rounded border border-emerald-400/50 text-emerald-200 bg-emerald-500/15 hover:bg-emerald-400/25 disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
      title="按已保存的人工干预策略重新执行诊断并对比"
    >
      ↻ 复盘重跑
    </button>

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
