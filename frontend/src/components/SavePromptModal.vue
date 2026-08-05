<script setup>
import { ref, watch } from 'vue'
import { store } from '../store'
import { respondSavePrompt, openSaveNaming } from '../ws'

const selected = ref(new Set())
const expanded = ref(false)

watch(() => store.savePrompt, (p) => {
  if (p) {
    selected.value = new Set((p.items || []).map((i) => i.id))
    expanded.value = false
  }
})

function toggle(id) {
  const s = new Set(selected.value)
  s.has(id) ? s.delete(id) : s.add(id)
  selected.value = s
}

// 注意：后端 save_prompt_response(save=true) 也会执行保存，
// 因此这里先用 save=false 消解提示（不保存），命名交由命名弹窗统一发送 save_strategy，
// 保证只保存一次；后端 prompt_save_strategy 为广播、不阻塞等待响应，不会悬挂。
function save() {
  respondSavePrompt(false)
  openSaveNaming()
  store.saveNaming.selected = [...selected.value]
  store.savePrompt = null
}

function ignore() {
  respondSavePrompt(false)
  store.savePrompt = null
}
</script>

<template>
  <div
    v-if="store.savePrompt"
    class="glass absolute left-1/2 -translate-x-1/2 bottom-1/3 w-[420px] rounded-xl pointer-events-auto overflow-hidden"
    style="box-shadow: 0 0 40px rgba(251,191,36,.3)"
  >
    <div class="flex items-center gap-2 px-4 py-2.5 bg-amber-500/10 border-b border-amber-400/30">
      <span class="w-2 h-2 rounded-full bg-amber-300 animate-pulse"></span>
      <span class="text-amber-200 text-sm font-bold">策略保存提醒</span>
    </div>

    <div class="px-4 py-3 text-xs text-slate-200 leading-relaxed">
      本轮复盘存在 <span class="text-amber-300 font-bold">{{ store.savePrompt.interventions }}</span> 项人工干预，勾选需要保存的项：
    </div>

    <!-- 干预清单（默认收起前 3 项，可展开） -->
    <div class="px-4 pb-2 space-y-1">
      <label
        v-for="it in (expanded ? store.savePrompt.items : store.savePrompt.items.slice(0, 3))"
        :key="it.id"
        class="flex items-start gap-2 text-[11px] text-slate-300 cursor-pointer rounded px-2 py-1 hover:bg-amber-500/10"
      >
        <input
          type="checkbox"
          :checked="selected.has(it.id)"
          @change="toggle(it.id)"
          class="accent-amber-400 mt-0.5"
        />
        <span>{{ it.label }}</span>
      </label>
      <button
        v-if="store.savePrompt.items.length > 3"
        @click="expanded = !expanded"
        class="text-[10px] text-amber-300/80 hover:text-amber-200 px-2"
      >{{ expanded ? '▲ 收起' : `▼ 展开全部 ${store.savePrompt.items.length} 项` }}</button>
    </div>

    <div class="flex justify-end gap-2 px-4 py-2.5 border-t border-amber-400/20 bg-slate-900/50">
      <button
        @click="ignore"
        class="text-xs px-3 py-1.5 rounded bg-slate-700/40 text-slate-300 border border-slate-500/40 hover:bg-slate-600/40"
      >忽略</button>
      <button
        @click="save"
        :disabled="!selected.size"
        class="text-xs font-bold px-3 py-1.5 rounded bg-amber-500/25 text-amber-200 border border-amber-400/50 hover:bg-amber-400/40 disabled:opacity-40 disabled:cursor-not-allowed"
      >保存所选（{{ selected.size }}）</button>
    </div>
  </div>
</template>
