<script setup>
import { store } from '../store'

function close() {
  store.historyModal = false
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
          暂无关联数据(报告生成后自动查询)
        </div>
        <template v-else>
          <div v-for="(s, i) in store.historyRelation.sections" :key="i" class="mb-4">
            <div class="text-violet-300 text-xs font-bold mb-1">{{ s.title }}</div>
            <div class="whitespace-pre-wrap text-slate-300">{{ s.answer }}</div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
