<script setup>
import { computed, defineComponent, h, ref, watch } from 'vue'
import { store } from '../store'

// 内联摘要卡组件：props { title, kind, data }
const SummaryCard = defineComponent({
  props: {
    title: { type: String, required: true },
    kind: { type: String, required: true }, // 'realtime' | 'replay'
    data: { type: Object, default: null },  // report_summary 事件体，null 表示无数据
  },
  setup(props) {
    const ACCENT = {
      realtime: {
        border: 'border-cyan-400/20',
        dot: 'bg-cyan-300',
        text: 'text-cyan-200',
        btn: 'bg-cyan-500/20 text-cyan-200 border-cyan-400/50 hover:bg-cyan-400/30',
      },
      replay: {
        border: 'border-emerald-400/20',
        dot: 'bg-emerald-300',
        text: 'text-emerald-200',
        btn: 'bg-emerald-500/20 text-emerald-200 border-emerald-400/50 hover:bg-emerald-400/30',
      },
    }
    const short = (t) => String(t ?? '—').replace('DiagnosisTool', '')
    const confPct = (c) => (c == null ? null : Math.round(c <= 1 ? c * 100 : c))
    const confClass = (c) => {
      const v = c <= 1 ? c : c / 100
      if (v >= 0.7) return 'text-emerald-300'
      if (v >= 0.4) return 'text-amber-300'
      return 'text-red-300'
    }
    function openReport() {
      store.reportModal = {
        title: `${props.kind === 'realtime' ? '实时' : '复盘'}诊断报告`,
        content: props.data?.report || '',
        meta: {
          line: props.data?.summary?.line_name,
          faultTime: props.data?.summary?.fault_time,
        },
      }
    }
    const field = (label, vnode) =>
      h('div', { class: 'flex items-center justify-between gap-2 py-0.5' }, [
        h('span', { class: 'text-slate-500 shrink-0' }, label),
        vnode,
      ])
    const textVal = (v, cls = 'text-slate-200') =>
      h('span', { class: `${cls} truncate` }, v == null || v === '' ? '—' : String(v))

    return () => {
      const a = ACCENT[props.kind] || ACCENT.realtime
      const d = props.data
      const s = d?.summary || {}
      const header = h('div', { class: `px-3 py-1.5 border-b ${a.border} flex items-center gap-2 shrink-0` }, [
        h('span', { class: `w-1.5 h-1.5 rounded-full ${a.dot}` }),
        h('span', { class: `${a.text} text-[11px] font-bold tracking-widest` }, props.title),
      ])

      if (!d) {
        return h('div', { class: 'glass rounded-lg flex flex-col overflow-hidden' }, [
          header,
          h('div', { class: 'px-4 py-5 text-center text-slate-500 italic text-[12px]' },
            props.kind === 'realtime' ? '等待诊断……' : '尚未复盘'),
        ])
      }

      const pct = confPct(s.confidence)
      const fields = h('div', { class: 'px-3 py-2 text-[11px] leading-snug' }, [
        field('线路名称', textVal(s.line_name)),
        field('电压等级', textVal(s.voltage_level)),
        field('故障时间', textVal(s.fault_time)),
        field('故障类型', textVal(s.fault_type)),
        field('置信度', pct == null
          ? textVal(null)
          : h('span', { class: `font-bold ${confClass(s.confidence)}` }, `${pct}%`)),
      ])

      const logs = d.action_log || s.action_log || []
      const tags = logs.length
        ? h('div', { class: 'px-3 pb-2 flex flex-wrap gap-1' },
            logs.map((l, i) =>
              h('span', {
                key: i,
                class: 'text-[10px] px-1.5 py-0.5 rounded border border-slate-600/50 bg-slate-800/60 text-slate-300',
              }, `${l.action_type || '干预'} ${short(l.tool_name || '')}`.trim())))
        : null

      const btn = h('div', { class: 'px-3 pb-2.5 mt-auto flex gap-2' }, [
        h('button', {
          class: `flex-1 text-[11px] font-bold py-1 rounded border ${a.btn}`,
          onClick: openReport,
        }, '查看报告'),
        h('button', {
          class: 'flex-1 text-[11px] font-bold py-1 rounded border bg-violet-500/20 text-violet-200 border-violet-400/50 hover:bg-violet-400/30',
          onClick: () => { store.historyModal = true },
        }, '历史关联'),
      ])

      return h('div', { class: 'glass rounded-lg flex flex-col overflow-hidden' }, [header, fields, tags, btn])
    }
  },
})

const lineTitle = computed(() => store.currentLine || store.lineText)
const canCompare = computed(() => !!store.summaries.realtime && !!store.summaries.replay)

// 报告流式生成中:实时区显示与自动滚动(纯文本轻量渲染,完成后由摘要卡接管)
const streaming = computed(() => !store.reportDone && store.report.length > 0)
const streamEl = ref(null)
watch(() => store.report, () => {
  const el = streamEl.value
  if (el) el.scrollTop = el.scrollHeight
})
</script>

<template>
  <aside class="glass rounded-lg flex flex-col pointer-events-auto h-full overflow-hidden">
    <!-- 头部：标题 + 线路 -->
    <div class="px-3 py-2 border-b border-cyan-500/20 shrink-0">
      <div class="flex items-center justify-between">
        <span class="text-cyan-300 text-xs font-bold tracking-widest">📋 诊断报告</span>
      </div>
      <div class="text-slate-300 text-[11px] mt-1 truncate">{{ lineTitle }}</div>
    </div>

    <!-- 报告生成中:流式实时输出(纯文本,完成后由摘要卡接管) -->
    <div v-if="streaming" class="border-b border-cyan-500/20 shrink-0 flex flex-col max-h-[38%]">
      <div class="px-3 py-1 text-cyan-400/80 text-[10px] font-bold tracking-widest flex items-center gap-1.5 shrink-0">
        <span class="w-1.5 h-1.5 rounded-full bg-cyan-300 animate-pulse"></span>报告生成中…
      </div>
      <div ref="streamEl" class="overflow-y-auto px-3 pb-2 whitespace-pre-wrap text-slate-300 text-[11px] leading-relaxed">{{ store.report }}</div>
    </div>

    <!-- 双摘要卡 -->
    <div class="flex-1 overflow-y-auto p-2 flex flex-col gap-2 min-h-0">
      <SummaryCard title="实时诊断" kind="realtime" :data="store.summaries.realtime" />
      <SummaryCard title="复盘诊断" kind="replay" :data="store.summaries.replay" />
    </div>

    <!-- 比对入口 -->
    <div v-if="canCompare" class="px-2 pb-2 shrink-0">
      <button
        @click="store.compareOpen = true"
        class="w-full text-[11px] font-bold py-1.5 rounded border bg-emerald-500/20 text-emerald-200 border-emerald-400/50 hover:bg-emerald-400/30"
      >比对</button>
    </div>
  </aside>
</template>
