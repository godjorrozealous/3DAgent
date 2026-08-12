<script setup>
import { computed } from 'vue'
import { store } from '../store'

const rt = computed(() => store.summaries.realtime)
const rp = computed(() => store.summaries.replay)

const short = (t) => String(t ?? '—').replace('DiagnosisTool', '')
const fmtW = (w) => Object.entries(w || {}).map(([t, v]) => `${short(t)}×${v}`).join('，') || '默认'
const fmtE = (e) => (e || []).map((t) => short(t)).join('，') || '无'
const fmtO = (o) => Object.entries(o || {}).map(([t, v]) => `${short(t)}:${v}`).join(';') || '无'

// 对比行（逻辑迁移自旧 ReplayPanel.vue，左列实时诊断，右列复盘诊断）
const rows = computed(() => {
  const b = rt.value || {}
  const r = rp.value || {}
  const bs = b.summary || {}
  const rs = r.summary || {}
  return [
    { label: '故障类型', base: bs.fault_type || '未知', replay: rs.fault_type || '未知', changed: (bs.fault_type || '未知') !== (rs.fault_type || '未知') },
    { label: '置信度', base: String(bs.confidence ?? '—'), replay: String(rs.confidence ?? '—'), changed: (bs.confidence ?? '—') !== (rs.confidence ?? '—') },
    { label: '主诊断工具', base: short(bs.primary_tool || '—'), replay: short(rs.primary_tool || '—'), changed: (bs.primary_tool || '—') !== (rs.primary_tool || '—') },
    { label: '工具权重', base: fmtW(b.weights), replay: fmtW(r.weights), changed: fmtW(b.weights) !== fmtW(r.weights) },
    { label: '排除工具', base: fmtE(b.excluded_tools), replay: fmtE(r.excluded_tools), changed: fmtE(b.excluded_tools) !== fmtE(r.excluded_tools) },
    { label: '数据修正', base: fmtO(b.overrides), replay: fmtO(r.overrides), changed: fmtO(b.overrides) !== fmtO(r.overrides) },
  ]
})

// 策略差异标签：复盘相对实时的 excluded/weights 差集
const diffTags = computed(() => {
  const tags = []
  const bEx = (rt.value?.excluded_tools || []).map(short)
  const rEx = (rp.value?.excluded_tools || []).map(short)
  for (const t of rEx) if (!bEx.includes(t)) tags.push({ text: `排除 ${t}`, cls: 'border-red-400/50 bg-red-500/15 text-red-200' })
  for (const t of bEx) if (!rEx.includes(t)) tags.push({ text: `恢复 ${t}`, cls: 'border-emerald-400/50 bg-emerald-500/15 text-emerald-200' })
  const bW = rt.value?.weights || {}
  const rW = rp.value?.weights || {}
  for (const t of new Set([...Object.keys(bW), ...Object.keys(rW)])) {
    const bv = bW[t]
    const rv = rW[t]
    if (bv === rv) continue
    if (rv != null) tags.push({ text: `${short(t)} ×${rv}`, cls: 'border-cyan-400/50 bg-cyan-500/15 text-cyan-200' })
    else tags.push({ text: `${short(t)} 恢复默认`, cls: 'border-emerald-400/50 bg-emerald-500/15 text-emerald-200' })
  }
  const rO = rp.value?.overrides || {}
  for (const t of Object.keys(rO)) {
    tags.push({ text: `${short(t)} 数据修正`, cls: 'border-amber-400/50 bg-amber-500/15 text-amber-200' })
  }
  for (const m of rp.value?.report_modifies || []) {
    tags.push({ text: `报告修改:${m}`, cls: 'border-violet-400/50 bg-violet-500/15 text-violet-200' })
  }
  return tags
})

function close() {
  store.compareOpen = false
}
</script>

<template>
  <div
    v-if="store.compareOpen"
    class="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center pointer-events-auto"
    @click.self="close"
  >
    <div
      class="glass w-full max-w-2xl max-h-[80vh] rounded-xl flex flex-col overflow-hidden mx-4"
      style="box-shadow: 0 0 50px rgba(52,211,153,.25)"
    >
      <!-- 标题栏 -->
      <div class="flex items-center justify-between px-4 py-2.5 bg-emerald-500/10 border-b border-emerald-400/30 shrink-0">
        <div class="flex items-center gap-2">
          <span class="w-2 h-2 rounded-full bg-emerald-300 animate-pulse"></span>
          <span class="text-emerald-200 text-sm font-bold">实时 / 复盘 诊断比对 · 干预策略生效验证</span>
        </div>
        <button @click="close" class="text-slate-400 hover:text-red-300 text-lg leading-none px-1">×</button>
      </div>

      <div class="flex-1 overflow-y-auto px-4 py-3 text-[12px]">
        <table class="w-full border-collapse">
          <thead>
            <tr class="text-slate-400 text-[11px]">
              <th class="text-left py-1 font-normal w-20">指标</th>
              <th class="text-left py-1 font-normal">实时诊断</th>
              <th class="text-left py-1 font-normal">复盘诊断</th>
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
          绿色「生效」标记表示该项相对实时诊断因人工干预策略发生了变化。
        </div>

        <!-- 策略差异标签 -->
        <div class="mt-4 pt-3 border-t border-slate-700/50">
          <div class="text-cyan-300 text-[11px] font-bold tracking-widest mb-2">策略差异标签</div>
          <div v-if="diffTags.length" class="flex flex-wrap gap-1.5">
            <span
              v-for="(tag, i) in diffTags" :key="i"
              class="text-[11px] px-2 py-0.5 rounded border"
              :class="tag.cls"
            >{{ tag.text }}</span>
          </div>
          <div v-else class="text-slate-500 text-[11px] italic">两次诊断的干预策略一致，无差异。</div>
        </div>
      </div>
    </div>
  </div>
</template>
