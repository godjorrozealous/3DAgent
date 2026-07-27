<script setup>
import { computed, ref, watch, nextTick } from 'vue'
import { store } from '../store'
import { sendChat, listTemplates, activateTemplate, deleteTemplate, listSkills, activateSkill, resetSkills } from '../ws'

const input = ref('')
const listEl = ref(null)
const fileInput = ref(null)
const uploading = ref(false)

const agent = computed(() => (store.chatTarget ? store.agents[store.chatTarget] : null))
const messages = computed(() => store.chatMessages[store.chatTarget] || [])
const hasMgmt = computed(() => store.chatTarget === 'audit' || store.chatTarget === 'commander')

watch(() => store.chatTarget, (target) => {
  if (target === 'audit') listTemplates()
  else if (target === 'commander') listSkills()
}, { immediate: true })

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

function triggerUpload() {
  if (fileInput.value) fileInput.value.click()
}

async function onUpload(e) {
  const file = e.target.files && e.target.files[0]
  if (!file) return
  uploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    await fetch('/api/templates/upload', { method: 'POST', body: fd })
    listTemplates()
  } finally {
    uploading.value = false
    e.target.value = ''
  }
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
    <div ref="listEl" class="overflow-y-auto px-4 py-3 space-y-2.5 font-mono text-[12px]" :class="hasMgmt ? 'h-40' : 'h-56'">
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

    <!-- 模板管理（审核员） -->
    <div v-if="store.chatTarget === 'audit'" class="border-t border-cyan-400/20 bg-slate-900/40 px-3 py-2">
      <div class="flex items-center justify-between mb-1.5">
        <span class="text-cyan-300 text-[11px] font-bold">模板管理</span>
        <button
          @click="triggerUpload"
          :disabled="uploading"
          class="text-[11px] px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-200 border border-cyan-400/40 hover:bg-cyan-400/30 disabled:opacity-50"
        >{{ uploading ? '上传中…' : '+ 上传模板' }}</button>
        <input ref="fileInput" type="file" accept=".md,.docx,.pdf" class="hidden" @change="onUpload" />
      </div>
      <div class="max-h-24 overflow-y-auto space-y-1 text-[11px]">
        <div v-if="!store.templates.length" class="text-slate-500 italic">暂无模板，可上传 .md/.docx/.pdf 文件</div>
        <div
          v-for="t in store.templates"
          :key="t.name"
          class="flex items-center justify-between gap-2 px-2 py-1 rounded border border-slate-600/40 bg-slate-800/50"
        >
          <div class="flex items-center gap-1.5 min-w-0">
            <span class="text-slate-200 truncate">{{ t.name }}</span>
            <span v-if="t.is_active" class="shrink-0 text-[10px] px-1.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-400/40">当前激活</span>
          </div>
          <div class="flex items-center gap-1 shrink-0">
            <button
              v-if="!t.is_active"
              @click="activateTemplate(t.name)"
              class="text-[10px] px-1.5 py-0.5 rounded bg-cyan-500/20 text-cyan-200 border border-cyan-400/40 hover:bg-cyan-400/30"
            >激活</button>
            <button
              @click="deleteTemplate(t.name)"
              class="text-[10px] px-1.5 py-0.5 rounded bg-red-500/15 text-red-300 border border-red-400/40 hover:bg-red-400/25"
            >删除</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 诊断策略（司令员） -->
    <div v-if="store.chatTarget === 'commander'" class="border-t border-cyan-400/20 bg-slate-900/40 px-3 py-2">
      <div class="text-cyan-300 text-[11px] font-bold mb-1.5">诊断策略</div>
      <div class="max-h-28 overflow-y-auto space-y-1 text-[11px]">
        <div v-if="!store.skills.length" class="text-slate-500 italic">暂无策略</div>
        <div
          v-for="s in store.skills"
          :key="s.name"
          class="flex items-center justify-between gap-2 px-2 py-1 rounded border border-slate-600/40 bg-slate-800/50"
        >
          <div class="min-w-0">
            <div class="flex items-center gap-1.5">
              <span class="text-slate-200 truncate">{{ s.name }}</span>
              <span
                class="shrink-0 text-[10px] px-1.5 rounded border"
                :class="s.is_default
                  ? 'bg-slate-600/30 text-slate-300 border-slate-500/40'
                  : 'bg-cyan-500/15 text-cyan-300 border-cyan-400/40'"
              >{{ s.is_default ? '系统' : '用户自定义' }}</span>
            </div>
            <div v-if="s.description" class="text-[10px] text-slate-500 truncate">{{ s.description }}</div>
          </div>
          <button
            @click="activateSkill(s.name)"
            :disabled="store.defaultSkill === s.name"
            class="shrink-0 text-[10px] px-1.5 py-0.5 rounded border"
            :class="store.defaultSkill === s.name
              ? 'bg-emerald-500/20 text-emerald-300 border-emerald-400/40 cursor-default'
              : 'bg-cyan-500/20 text-cyan-200 border-cyan-400/40 hover:bg-cyan-400/30'"
          >{{ store.defaultSkill === s.name ? '已激活' : '激活' }}</button>
        </div>
      </div>
      <div class="flex justify-end mt-1.5">
        <button
          @click="resetSkills()"
          class="text-[10px] px-2 py-0.5 rounded bg-slate-700/40 text-slate-300 border border-slate-500/40 hover:bg-slate-600/40"
        >重置默认</button>
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
