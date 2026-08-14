<script setup>
import { computed, ref } from 'vue'
import { store } from '../store'
import { requestRecord, setView, deleteRecords } from '../ws'

const keyword = ref('')

const selected = ref(new Set())
const confirmDelete = ref(null) // { ids: number[], lines: string[] }

const allSelected = computed(() =>
  filtered.value.length > 0 && filtered.value.every((r) => selected.value.has(r.id)))

function toggleAll() {
  selected.value = allSelected.value
    ? new Set()
    : new Set(filtered.value.map((r) => r.id))
}

// 行右键菜单(单删入口,替代行内按钮防误点)
const menu = ref(null) // { x, y, id }

function openMenu(e, id) {
  menu.value = {
    x: Math.min(e.clientX, window.innerWidth - 140),
    y: Math.min(e.clientY, window.innerHeight - 60),
    id,
  }
}

function closeMenu() {
  menu.value = null
}

function menuDelete() {
  const id = menu.value?.id
  closeMenu()
  if (id != null) askDelete([id])
}

function toggleSelect(id) {
  const s = new Set(selected.value)
  if (s.has(id)) s.delete(id); else s.add(id)
  selected.value = s
}

function askDelete(ids) {
  const lines = store.records.filter((r) => ids.includes(r.id))
    .map((r) => `#${r.id} ${r.line} (${r.time})`)
  confirmDelete.value = { ids, lines }
}

function doDelete() {
  const ids = confirmDelete.value?.ids || []
  if (ids.length) deleteRecords(ids)
  if (store.recordDetail && ids.includes(store.recordDetail.id)) store.recordDetail = null
  selected.value = new Set()
  confirmDelete.value = null
}

const filtered = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return store.records
  return store.records.filter((r) =>
    [r.line, r.time, ...(r.strategies || []), ...(r.objections || [])]
      .join(' ').toLowerCase().includes(k))
})

function viewReport(title, content, summary) {
  store.reportModal = {
    title,
    content: content || '（空）',
    meta: { line: store.recordDetail?.line, faultTime: summary?.fault_time },
  }
}

function objectionText(o) {
  return o.text || `${o.tool || ''} ${o.decision || ''}${o.value != null ? ' = ' + o.value : ''}`
}
</script>

<template>
  <div class="absolute inset-0 z-10 bg-slate-950/95 flex flex-col p-4 gap-3 overflow-hidden pointer-events-auto" @click="closeMenu">
    <div class="flex items-center gap-3 shrink-0">
      <span class="text-cyan-300 font-bold text-sm tracking-widest">◈ 诊断结果集</span>
      <input
        v-model="keyword"
        placeholder="关键字搜索（线路 / 策略 / 复盘要求）…"
        class="flex-1 max-w-md bg-slate-900/80 border border-cyan-500/30 rounded px-3 py-1.5 text-xs text-cyan-100 outline-none focus:border-cyan-300 placeholder:text-slate-600"
      />
      <button
        v-if="selected.size"
        @click="askDelete([...selected])"
        class="text-xs px-3 py-1.5 rounded border border-red-400/50 text-red-200 bg-red-500/15 hover:bg-red-400/25"
      >删除选中({{ selected.size }})</button>
      <button
        @click="setView('room')"
        class="text-xs px-3 py-1.5 rounded border border-cyan-400/50 text-cyan-200 bg-cyan-500/15 hover:bg-cyan-400/25"
      >返回指挥室</button>
    </div>

    <div class="flex-1 flex gap-3 min-h-0">
      <!-- 记录列表 -->
      <div class="w-[380px] shrink-0 glass rounded-lg overflow-y-auto">
        <div class="flex items-center gap-2 px-3 py-1.5 border-b border-slate-700/50 text-[10px] text-slate-500">
          <input
            type="checkbox" :checked="allSelected" @change="toggleAll"
            class="accent-red-400"
          />
          <span>全选(当前列表 {{ filtered.length }} 条)</span>
        </div>
        <div
          v-for="r in [...filtered].reverse()" :key="r.id"
          @click="requestRecord(r.id)"
          @contextmenu.prevent="openMenu($event, r.id)"
          class="px-3 py-2 border-b border-slate-700/40 cursor-pointer hover:bg-cyan-500/10 flex items-start gap-2"
          :class="store.recordDetail?.id === r.id ? 'bg-cyan-500/15' : ''"
        >
          <input
            type="checkbox" :checked="selected.has(r.id)"
            @click.stop="toggleSelect(r.id)"
            class="mt-0.5 accent-red-400 shrink-0"
          />
          <div class="flex-1 min-w-0">
            <div class="text-xs text-cyan-100 truncate" :title="r.line">{{ r.line }}</div>
            <div class="text-[10px] text-slate-500 mt-0.5 flex gap-2 flex-wrap">
              <span>#{{ r.id }} · {{ r.time }}</span>
              <span v-if="r.has_replay" class="text-emerald-300">已复盘</span>
              <span v-for="s in r.strategies" :key="s" class="text-fuchsia-300">{{ s }}</span>
            </div>
          </div>
        </div>
        <div v-if="!filtered.length" class="text-slate-600 text-xs text-center py-8">暂无记录</div>
      </div>

      <!-- 详情 -->
      <div class="flex-1 glass rounded-lg overflow-y-auto p-4 min-w-0">
        <template v-if="store.recordDetail">
          <div class="text-cyan-200 text-sm font-bold mb-1">{{ store.recordDetail.line }}</div>
          <div class="text-[10px] text-slate-500 mb-3">#{{ store.recordDetail.id }} · {{ store.recordDetail.time }}</div>

          <div class="flex gap-2 mb-3 flex-wrap">
            <button
              v-if="store.recordDetail.realtime"
              @click="viewReport('实时诊断报告', store.recordDetail.realtime.report, store.recordDetail.realtime.summary)"
              class="text-xs px-3 py-1.5 rounded bg-cyan-500/20 text-cyan-200 border border-cyan-400/40 hover:bg-cyan-400/30"
            >实时诊断报告</button>
            <button
              v-for="(rp, i) in store.recordDetail.replays" :key="i"
              @click="viewReport('复盘报告' + (store.recordDetail.replays.length > 1 ? ' ' + (i + 1) : ''), rp.report, rp.summary)"
              class="text-xs px-3 py-1.5 rounded bg-emerald-500/20 text-emerald-200 border border-emerald-400/40 hover:bg-emerald-400/30"
            >复盘报告{{ store.recordDetail.replays.length > 1 ? ' ' + (i + 1) : '' }}</button>
          </div>

          <div v-if="store.recordDetail.objections?.length" class="mb-3">
            <div class="text-amber-300 text-[10px] font-bold mb-1">复盘要求与异议</div>
            <div
              v-for="(o, i) in store.recordDetail.objections" :key="i"
              class="text-[11px] text-slate-300 border border-slate-600/40 bg-slate-800/50 rounded px-2 py-1 mb-1"
            >
              <span class="text-slate-500">[{{ o.kind }} {{ o.time }}]</span> {{ objectionText(o) }}
            </div>
          </div>

          <div v-if="store.recordDetail.strategies?.length">
            <div class="text-fuchsia-300 text-[10px] font-bold mb-1">保存的策略</div>
            <span
              v-for="s in store.recordDetail.strategies" :key="s"
              class="inline-block text-[11px] px-1.5 py-0.5 mr-1 rounded bg-fuchsia-500/15 border border-fuchsia-400/40 text-fuchsia-200"
            >{{ s }}</span>
          </div>
        </template>
        <div v-else class="text-slate-600 text-xs text-center py-16">选择左侧记录查看详情</div>
      </div>
    </div>

    <div
      v-if="confirmDelete"
      class="absolute inset-0 z-20 bg-slate-950/70 flex items-center justify-center"
      @click.self="confirmDelete = null"
    >
      <div class="glass rounded-lg p-4 w-[360px] border border-red-400/30">
        <div class="text-red-300 text-sm font-bold mb-2">确认删除 {{ confirmDelete.ids.length }} 条记录?</div>
        <div class="text-[11px] text-slate-300 mb-3 max-h-32 overflow-y-auto">
          <div v-for="l in confirmDelete.lines" :key="l" class="py-0.5">{{ l }}</div>
        </div>
        <div class="text-[10px] text-slate-500 mb-3">删除后不可恢复。</div>
        <div class="flex justify-end gap-2">
          <button
            @click="confirmDelete = null"
            class="text-xs px-3 py-1.5 rounded border border-slate-500/50 text-slate-300 hover:bg-slate-700/30"
          >取消</button>
          <button
            @click="doDelete"
            class="text-xs px-3 py-1.5 rounded border border-red-400/50 text-red-200 bg-red-500/20 hover:bg-red-400/30"
          >确认删除</button>
        </div>
      </div>
    </div>
    <div
      v-if="menu"
      class="fixed z-30 glass rounded border border-slate-600/50 py-1 w-[130px]"
      :style="{ left: menu.x + 'px', top: menu.y + 'px' }"
      @click.stop
    >
      <button
        @click="menuDelete"
        class="w-full text-left text-[11px] px-3 py-1.5 text-red-300 hover:bg-red-500/15"
      >删除该记录</button>
    </div>
  </div>
</template>
