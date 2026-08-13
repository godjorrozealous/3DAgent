<script setup>
import { ref, computed } from 'vue'
import { store } from '../store'
import { setView, deleteStrategies, listStrategies, activateSkill } from '../ws'

const selected = ref(new Set())
const confirming = ref(false)

function toggle(name) {
  if (name === store.strategiesDefault) return
  const s = new Set(selected.value)
  s.has(name) ? s.delete(name) : s.add(name)
  selected.value = s
}

const deletable = computed(() =>
  store.strategiesList.filter((s) => s.name !== store.strategiesDefault))

function toggleAll() {
  selected.value = selected.value.size === deletable.value.length
    ? new Set()
    : new Set(deletable.value.map((s) => s.name))
}

async function doDelete() {
  deleteStrategies([...selected.value])
  selected.value = new Set()
  confirming.value = false
}
</script>

<template>
  <div class="absolute inset-0 z-10 bg-slate-950/95 flex flex-col p-4 gap-3 overflow-hidden pointer-events-auto">
    <div class="flex items-center gap-3 shrink-0">
      <span class="text-fuchsia-300 font-bold text-sm tracking-widest">◈ 干预策略管理</span>
      <button @click="listStrategies" class="text-xs px-3 py-1.5 rounded border border-slate-400/40 text-slate-300 bg-slate-700/30 hover:bg-slate-600/40">刷新</button>
      <button
        v-if="!confirming"
        :disabled="!selected.size"
        @click="confirming = true"
        class="text-xs px-3 py-1.5 rounded border border-red-400/50 text-red-300 bg-red-500/15 hover:bg-red-400/25 disabled:opacity-40 disabled:cursor-not-allowed"
      >删除所选（{{ selected.size }}）</button>
      <template v-else>
        <span class="text-xs text-red-300">确认删除 {{ selected.size }} 项策略？不可恢复。</span>
        <button @click="doDelete" class="text-xs font-bold px-3 py-1.5 rounded border border-red-400/60 text-red-200 bg-red-500/25 hover:bg-red-400/40">确认删除</button>
        <button @click="confirming = false" class="text-xs px-3 py-1.5 rounded border border-slate-500/40 text-slate-300 bg-slate-700/30">取消</button>
      </template>
      <button @click="setView('room')" class="ml-auto text-xs px-3 py-1.5 rounded border border-cyan-400/50 text-cyan-200 bg-cyan-500/15 hover:bg-cyan-400/25">返回指挥室</button>
    </div>

    <div class="flex-1 glass rounded-lg overflow-y-auto min-h-0">
      <div class="flex items-center gap-3 px-3 py-2 border-b border-slate-700/50 text-[10px] text-slate-500">
        <input type="checkbox"
          :checked="deletable.length && selected.size === deletable.length"
          @change="toggleAll" class="accent-fuchsia-400" />
        <span class="w-56">策略名</span>
        <span class="flex-1">描述</span>
        <span class="w-20">来源</span>
        <span class="w-16">状态</span>
      </div>
      <div
        v-for="s in store.strategiesList" :key="s.name"
        class="flex items-center gap-3 px-3 py-2 border-b border-slate-700/30 text-xs"
        :class="selected.has(s.name) ? 'bg-fuchsia-500/10' : ''"
      >
        <input
          type="checkbox"
          :checked="selected.has(s.name)"
          :disabled="s.name === store.strategiesDefault"
          @change="toggle(s.name)"
          class="accent-fuchsia-400 disabled:opacity-30"
        />
        <span class="w-56 truncate text-fuchsia-100" :title="s.name">{{ s.name }}</span>
        <span class="flex-1 truncate text-slate-400" :title="s.description">{{ s.description || '—' }}</span>
        <span class="w-20 text-slate-500">{{ s.source }}</span>
        <span class="w-16">
          <span v-if="s.name === store.strategiesDefault"
            class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 border border-emerald-400/40 text-emerald-300"
          >使用中</span>
          <button v-else
            @click="activateSkill(s.name)"
            class="text-[10px] px-1.5 py-0.5 rounded border border-cyan-400/50 text-cyan-200 bg-cyan-500/15 hover:bg-cyan-400/25"
          >激活</button>
        </span>
      </div>
      <div v-if="!store.strategiesList.length" class="px-3 py-6 text-center text-xs text-slate-600">
        暂无策略。复盘完成并提出异议后，可在保存提示中生成策略。
      </div>
    </div>
  </div>
</template>
