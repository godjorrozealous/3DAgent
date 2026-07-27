<script setup>
import { computed } from 'vue'
import { store } from '../store'

const compare = computed(() => store.compare)

const rows = computed(() => {
  if (!compare.value) return []
  const b = compare.value.baseline || {}
  const r = compare.value.replay || {}
  const bs = b.summary || {}
  const rs = r.summary || {}
  const fmtW = (w) => Object.entries(w || {}).map(([t, v]) => `${t.replace('DiagnosisTool', '')}×${v}`).join('，') || '默认'
  const fmtE = (e) => (e || []).map((t) => t.replace('DiagnosisTool', '')).join('，') || '无'
  return [
    { label: '故障类型', base: bs.fault_type || '未知', replay: rs.fault_type || '未知', changed: (bs.fault_type || '未知') !== (rs.fault_type || '未知') },
    { label: '置信度', base: String(bs.confidence ?? '—'), replay: String(rs.confidence ?? '—'), changed: (bs.confidence ?? '—') !== (rs.confidence ?? '—') },
    { label: '主诊断工具', base: (bs.primary_tool || '—').replace('DiagnosisTool', ''), replay: (rs.primary_tool || '—').replace('DiagnosisTool', ''), changed: (bs.primary_tool || '—') !== (rs.primary_tool || '—') },
    { label: '工具权重', base: fmtW(b.weights), replay: fmtW(r.weights), changed: fmtW(b.weights) !== fmtW(r.weights) },
    { label: '排除工具', base: fmtE(b.excluded_tools), replay: fmtE(r.excluded_tools), changed: fmtE(b.excluded_tools) !== fmtE(r.excluded_tools) },
  ]
})

function close() {
  store.compare = null
}
</script>

<template>
  <div
    v-if="compare"
    class="glass absolute bottom-24 right-4 w-[430px] rounded-xl pointer-events-auto flex flex-col overflow-hidden"
    style="box-shadow: 0 0 40px rgba(52,211,153,.2)"
  >
    <div class="flex items-center justify-between px-4 py-2.5 bg-emerald-500/10 border-b border-emerald-400/30">
      <div class="flex items-center gap-2">
        <span class="w-2 h-2 rounded-full bg-emerald-300 animate-pulse"></span>
        <span class="text-emerald-200 text-sm font-bold">复盘对比 · 干预策略生效验证</span>
      </div>
      <button @click="close" class="text-slate-400 hover:text-red-300 text-lg leading-none px-1">×</button>
    </div>

    <div class="px-4 py-3 text-[12px]">
      <table class="w-full border-collapse">
        <thead>
          <tr class="text-slate-400 text-[11px]">
            <th class="text-left py-1 font-normal w-20">指标</th>
            <th class="text-left py-1 font-normal">基线诊断</th>
            <th class="text-left py-1 font-normal">复盘重跑</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.label" class="border-t border-slate-700/50">
            <td class="py-1.5 text-slate-400">{{ row.label }}</td>
            <td class="py-1.5 text-slate-200 pr-2">{{ row.base }}</td>
            <td class="py-1.5" :class="row.changed ? 'text-emerald-300 font-bold' : 'text-slate-200'">
              {{ row.replay }}
              <span v-if="row.changed" class="text-[10px] ml-1 px-1 rounded bg-emerald-500/20 border border-emerald-400/40">生效</span>
            </td>
          </tr>
        </tbody>
      </table>
      <div class="text-slate-500 text-[10px] mt-2">
        绿色「生效」标记表示该项相对基线因人工干预策略发生了变化。
      </div>
    </div>
  </div>
</template>
