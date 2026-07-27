<script setup>
import { computed, ref, watch, nextTick } from 'vue'
import { store } from '../store'
import { sendChat } from '../ws'

const input = ref('')
const listEl = ref(null)

const agent = computed(() => (store.chatTarget ? store.agents[store.chatTarget] : null))
const messages = computed(() => store.chatMessages[store.chatTarget] || [])

watch(messages, async () => {
  await nextTick()
  if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
}, { deep: true })

function submit() {
  const text = input.value.trim()
  if (!text || !store.chatTarget) return
  sendChat(store.chatTarget, text)
  input.value = ''
}

function close() {
  store.chatTarget = null
}
</script>

<template>
  <div
    v-if="agent"
    class="glass absolute bottom-24 left-1/2 -translate-x-1/2 w-[420px] rounded-xl pointer-events-auto flex flex-col overflow-hidden"
    style="box-shadow: 0 0 40px rgba(34,211,238,.25)"
  >
    <!-- 标题栏 -->
    <div class="flex items-center justify-between px-4 py-2.5 bg-cyan-500/10 border-b border-cyan-400/30">
      <div class="flex items-center gap-2">
        <span class="w-2 h-2 rounded-full bg-cyan-300 animate-pulse"></span>
        <span class="text-cyan-200 text-sm font-bold">{{ agent.name }} · 直连频道</span>
      </div>
      <button @click="close" class="text-slate-400 hover:text-red-300 text-lg leading-none px-1">×</button>
    </div>

    <!-- 消息区 -->
    <div ref="listEl" class="h-56 overflow-y-auto px-4 py-3 space-y-2.5 font-mono text-[12px]">
      <div class="text-slate-500 italic text-[11px]">
        已建立与「{{ agent.name }}」的加密直连。司令员可执行真实干预，例如："排除鸟害工具"、"将雷电工具权重调整为 1.5"、"恢复覆冰工具"
      </div>
      <div v-for="(m, i) in messages" :key="i" class="flex" :class="m.from === 'user' ? 'justify-end' : 'justify-start'">
        <div
          class="max-w-[85%] rounded-lg px-3 py-1.5"
          :class="m.from === 'user'
            ? 'bg-cyan-500/20 text-cyan-100 border border-cyan-400/40'
            : 'bg-slate-800/70 text-slate-200 border border-slate-600/50'"
        >
          <div class="text-[10px] opacity-60 mb-0.5">{{ m.from === 'user' ? '指挥员' : agent.name }} · {{ m.time }}</div>
          {{ m.message }}
        </div>
      </div>
    </div>

    <!-- 输入区 -->
    <div class="flex gap-2 px-3 py-2.5 border-t border-cyan-400/20 bg-slate-900/50">
      <input
        v-model="input"
        @keyup.enter="submit"
        placeholder="输入干预指令，回车发送…"
        class="flex-1 bg-slate-900/80 border border-cyan-500/30 rounded px-3 py-1.5 text-xs text-cyan-100 outline-none focus:border-cyan-300 placeholder:text-slate-600"
      />
      <button
        @click="submit"
        class="text-xs font-bold px-3.5 rounded bg-cyan-500/25 text-cyan-200 border border-cyan-400/50 hover:bg-cyan-400/40"
      >发送</button>
    </div>
  </div>
</template>
