<script setup>
import { computed, ref, watch, nextTick } from 'vue'
import { store } from '../store'

const listEl = ref(null)
const logs = computed(() => store.logs)
watch(logs, async () => {
  await nextTick()
  if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
}, { deep: true })

const agentColor = (id) => ({
  commander: 'text-cyan-300',
  lightning: 'text-yellow-300',
  wind: 'text-sky-300',
  icing: 'text-indigo-300',
  bird: 'text-orange-300',
  audit: 'text-fuchsia-300',
}[id] || 'text-slate-300')
</script>

<template>
  <aside class="glass rounded-lg flex flex-col min-h-0 pointer-events-auto h-full">
    <div class="px-3 py-2 border-b border-cyan-500/20 text-cyan-300 text-xs font-bold tracking-widest">
      ◢ 智能体实时事件流
    </div>
    <div ref="listEl" class="flex-1 min-h-0 overflow-y-auto px-3 py-2 space-y-1.5 font-mono text-[11px] leading-relaxed">
      <div v-if="!logs.length" class="text-slate-500 italic">等待任务下发……</div>
      <div v-for="(l, i) in logs" :key="i" class="flex gap-1.5">
        <span class="text-slate-500 shrink-0">[{{ l.time }}]</span>
        <span :class="agentColor(l.agent)" class="shrink-0">{{ l.agent_name }}:</span>
        <span class="text-slate-300">{{ l.message }}</span>
      </div>
    </div>
  </aside>
</template>
