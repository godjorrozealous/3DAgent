import { store, pushLog, pushChat } from './store'

let ws = null
const listeners = new Set()

// HMR 安全：模块热替换时关闭旧 socket 并清空监听器，
// 否则旧实例的连接残留会与实例并存，所有事件被重复写入 store（日志/确认队列翻倍）
if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    if (ws) {
      ws.onclose = null
      ws.close()
      ws = null
    }
    listeners.clear()
  })
  import.meta.hot.accept(() => connect())
}

export function onEvent(fn) {
  listeners.add(fn)
}

function emit(event) {
  listeners.forEach((fn) => fn(event))
}

function handle(event) {
  switch (event.type) {
    case 'init':
      event.agents.forEach((a) => (store.agents[a.id] = a))
      store.strategies = event.strategies || []
      store.sessionId = event.session_id
      // 刷新/重连时恢复运行态（诊断中途刷新页面不再显示为闲置）
      store.running = !!event.running
      store.replayMode = event.mode === 'replay'
      break
    case 'agent_status': {
      const a = store.agents[event.agent]
      if (a) a.status = event.status
      if (event.agent === 'commander') {
        store.running = event.status === 'running'
      }
      emit(event)
      break
    }
    case 'log':
      pushLog(event)
      break
    case 'report':
      if (event.reset) {
        store.report = ''
        store.reportDone = false
        store.reportGenerating = false
      } else if (event.delta != null) {
        store.report += event.delta        // 流式增量拼接
        store.reportDone = false
        store.reportGenerating = true      // 仅报告 LLM 流式(delta)点亮「正在生成报告」
      } else {
        store.report = event.content       // 全量(工具阶段子报告/complete 覆盖)
        store.reportDone = event.done
        if (event.done) store.reportGenerating = false
      }
      break
    case 'chat':
      pushChat(event.agent, event)
      break
    case 'session_snapshot':
      store.sessionId = event.session_id
      store.weights = event.weights || {}
      store.excludedTools = event.excluded_tools || []
      store.plannedTools = event.planned_tools || []
      store.valueOverrides = event.overrides || {}
      emit(event)
      break
    case 'report_summary':
      store.summaries[event.kind] = event
      // 历史关联由后端在诊断启动时即后台预取，完成会主动广播；
      // 此处仅在尚未就绪时补一次请求（如后端重启错过预取），ready 则不重复获取
      if (store.historyRelation.status !== 'ready') {
        store.historyRelation = { status: 'loading', sections: [], error: '' }
        send({ type: 'history_relation' })
      }
      break
    case 'prompt_save_strategy':
      store.savePrompt = { interventions: event.interventions, items: event.items || [], context: event.context }
      break
    case 'objection_accepted':
      store.agentBusy[event.agent] = true
      // 对话异议视为该工具已确认：从确认队列移除，弹窗关闭/提交后推进到下一个
      {
        const i = store.confirmQueue.findIndex(
          (e) => e.agent === event.agent || e.tool === event.tool
        )
        if (i >= 0) store.confirmQueue.splice(i, 1)
      }
      break
    case 'tool_confirm_request':
      store.agentBusy[event.agent] = false
      store.confirmQueue.push(event)
      // 不抢占已打开的会话弹窗（确认或私聊），提交后由弹窗按队列推进
      if (!store.agentSession) store.agentSession = { ...event, confirm: true }
      break
    case 'report_review_request':
      store.reportReviewPending = true
      store.reportReviewEmpty = !!event.empty
      break
    case 'confirm_queue_clear':
      store.confirmQueue.length = 0
      store.reportReviewPending = false
      store.reportReviewEmpty = false
      store.agentSession = null
      store.agentBusy = {}
      break
    case 'run_state':
      store.replayMode = event.mode === 'replay'
      store.running = event.mode !== null
      store.reportKind = event.mode        // 本轮报告归属:realtime | replay | null
      store.reportGenerating = false
      if (event.mode === 'realtime') {
        // 新实时诊断:上一条线路的双摘要卡与比对数据属陈旧数据,清空
        // (replay 启动不清——实时卡是比对的基线)
        store.summaries.realtime = null
        store.summaries.replay = null
        store.compare = null
        if (store.compareOpen) store.compareOpen = false
        store.historyRelation = { status: 'idle', sections: [], error: '' }
      }
      break
    case 'templates':
      store.templates = event.templates
      break
    case 'skills':
      store.skills = event.skills
      store.defaultSkill = event.default_skill
      emit(event)
      break
    case 'strategies_list':
      store.strategiesList = event.strategies || []
      store.strategiesDefault = event.default || ''
      break
    case 'strategy_saved':
      store.strategies.push(event.strategy)
      break
    case 'history_relation':
      store.historyRelation = event.error
        ? { status: 'error', sections: [], error: event.error }
        : { status: 'ready', sections: event.sections || [], error: '' }
      break
    case 'replay_compare':
      store.compare = event
      break
    case 'diagnosis_queue':
      store.currentLine = event.current || ''
      store.diagQueue = event.queue || []
      break
    case 'records_list':
      store.records = event.records || []
      break
    case 'record_detail':
      store.recordDetail = event.record
      break
  }
}

export function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  ws = new WebSocket(`${proto}://${location.host}/ws`)
  ws.onopen = () => (store.connected = true)
  ws.onclose = () => {
    store.connected = false
    setTimeout(connect, 2000)
  }
  ws.onerror = () => ws.close()
  ws.onmessage = (e) => handle(JSON.parse(e.data))
}

export function send(data) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(data))
}

export function startDiagnosis() {
  const text = store.lineText.trim()
  if (text) send({ type: 'start_diagnosis', text })
}

// 命名保存：本地时间 策略_YYYYMMDD_HHmm（pad 补零，非 UTC）
export function openSaveNaming() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  const suggested = `策略_${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`
  store.saveNaming = { suggested }
}

export function saveStrategyNamed(name) {
  const items = store.saveNaming?.selected ?? null
  send({ type: 'save_strategy', name, items })
}

export function replay() {
  store.compare = null
  send({ type: 'replay' })
}

export function sendChat(agent, message) {
  pushChat(agent, {
    from: 'user',
    message,
    time: new Date().toTimeString().slice(0, 8),
  })
  send({ type: 'chat', agent, message })
}

// 快捷按钮指令回显：仅本地气泡，不转发后端/PLD。
// 复盘确认快捷按钮的真实决策走 tool_confirm_response；若再作为 chat 转发 PLD，
// 会被意图分类器误判为新诊断并劫持活跃会话，导致后续干预「无法调整」
export function echoChat(agent, message) {
  pushChat(agent, {
    from: 'user',
    message,
    time: new Date().toTimeString().slice(0, 8),
  })
}

export const listTemplates = () => send({ type: 'list_templates' })
export const activateTemplate = (name) => send({ type: 'activate_template', name })
export const deleteTemplate = (name) => send({ type: 'delete_template', name })
export const listSkills = () => send({ type: 'list_skills' })
export const activateSkill = (name) => send({ type: 'activate_skill', name })
export const resetSkills = () => send({ type: 'reset_skills' })
export const sendToolConfirm = (tool, decision, value) =>
  send({ type: 'tool_confirm_response', tool, decision, value })
export const sendReportReview = (satisfied, instruction, kind) =>
  send({ type: 'report_review_response', satisfied, instruction, kind })
export const respondSavePrompt = (save, name) =>
  send({ type: 'save_prompt_response', save, name })
export const cancelQueued = (index) => send({ type: 'cancel_queued', index })
export const requestRecords = () => send({ type: 'list_records' })
export const requestRecord = (id) => send({ type: 'get_record', id })
export const requestHistoryRelation = () => send({ type: 'history_relation' })
// 打开历史关联弹窗：预取未命中（idle/error）时补发查询；loading/ready 直接展示现状
export function openHistoryModal() {
  store.historyModal = true
  const st = store.historyRelation.status
  if (st === 'idle' || st === 'error') {
    store.historyRelation = { status: 'loading', sections: [], error: '' }
    send({ type: 'history_relation' })
  }
}
export const deleteRecords = (ids) => send({ type: 'delete_records', ids })
export const listStrategies = () => send({ type: 'list_strategies' })
export const deleteStrategies = (names) => send({ type: 'delete_strategies', names })
export function setView(v) {
  store.view = v
  if (v === 'history') requestRecords()
  if (v === 'strategies') listStrategies()
}
