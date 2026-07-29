<script setup>
import { ref, watch } from 'vue'
import { store } from '../store'
import { saveStrategyNamed } from '../ws'

const name = ref('')

// 打开弹窗时用后端/本地建议名预填
watch(() => store.saveNaming, (v) => {
  if (v) name.value = v.suggested || ''
})

function save() {
  const n = name.value.trim()
  if (!n) return
  saveStrategyNamed(n)
  store.saveNaming = null
}

function cancel() {
  store.saveNaming = null
}
</script>

<template>
  <div
    v-if="store.saveNaming"
    class="glass absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-96 rounded-xl pointer-events-auto overflow-hidden"
    style="box-shadow: 0 0 40px rgba(217,70,239,.3)"
  >
    <!-- 标题栏 -->
    <div class="flex items-center gap-2 px-4 py-2.5 bg-fuchsia-500/10 border-b border-fuchsia-400/30">
      <span class="w-2 h-2 rounded-full bg-fuchsia-300 animate-pulse"></span>
      <span class="text-fuchsia-200 text-sm font-bold">保存诊断策略</span>
    </div>

    <!-- 内容 -->
    <div class="px-4 py-3 space-y-2">
      <input
        v-model="name"
        @keyup.enter="save"
        placeholder="输入策略名称…"
        class="w-full bg-slate-900/80 border border-fuchsia-500/40 rounded px-3 py-1.5 text-xs text-fuchsia-100 outline-none focus:border-fuchsia-300 placeholder:text-slate-600"
      />
      <div class="text-[11px] text-slate-400 leading-relaxed">将保存当前权重/排除及本轮干预线索</div>
    </div>

    <!-- 按钮区 -->
    <div class="flex justify-end gap-2 px-4 py-2.5 border-t border-fuchsia-400/20 bg-slate-900/50">
      <button
        @click="cancel"
        class="text-xs px-3 py-1.5 rounded bg-slate-700/40 text-slate-300 border border-slate-500/40 hover:bg-slate-600/40"
      >取消</button>
      <button
        @click="save"
        :disabled="!name.trim()"
        class="text-xs font-bold px-3 py-1.5 rounded bg-fuchsia-500/25 text-fuchsia-200 border border-fuchsia-400/50 hover:bg-fuchsia-400/40 disabled:opacity-40 disabled:cursor-not-allowed"
      >保存</button>
    </div>
  </div>
</template>
