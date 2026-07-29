<script setup>
import { store } from '../store'
import { respondSavePrompt, openSaveNaming } from '../ws'

// 注意：后端 save_prompt_response(save=true) 也会执行保存，
// 因此这里先用 save=false 消解提示（不保存），命名交由命名弹窗统一发送 save_strategy，
// 保证只保存一次；后端 prompt_save_strategy 为广播、不阻塞等待响应，不会悬挂。
function save() {
  respondSavePrompt(false)
  openSaveNaming()
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
    class="glass absolute left-1/2 -translate-x-1/2 bottom-1/3 w-[380px] rounded-xl pointer-events-auto overflow-hidden"
    style="box-shadow: 0 0 40px rgba(251,191,36,.3)"
  >
    <!-- 标题栏 -->
    <div class="flex items-center gap-2 px-4 py-2.5 bg-amber-500/10 border-b border-amber-400/30">
      <span class="w-2 h-2 rounded-full bg-amber-300 animate-pulse"></span>
      <span class="text-amber-200 text-sm font-bold">策略保存提醒</span>
    </div>

    <!-- 内容 -->
    <div class="px-4 py-3 text-xs text-slate-200 leading-relaxed">
      本轮存在 <span class="text-amber-300 font-bold">{{ store.savePrompt.interventions }}</span> 项人工干预，是否保存为诊断策略？
    </div>

    <!-- 按钮区 -->
    <div class="flex justify-end gap-2 px-4 py-2.5 border-t border-amber-400/20 bg-slate-900/50">
      <button
        @click="ignore"
        class="text-xs px-3 py-1.5 rounded bg-slate-700/40 text-slate-300 border border-slate-500/40 hover:bg-slate-600/40"
      >忽略</button>
      <button
        @click="save"
        class="text-xs font-bold px-3 py-1.5 rounded bg-amber-500/25 text-amber-200 border border-amber-400/50 hover:bg-amber-400/40"
      >保存策略</button>
    </div>
  </div>
</template>
