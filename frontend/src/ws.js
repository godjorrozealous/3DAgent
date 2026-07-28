import { store, pushLog, pushChat, LINES } from './store'

let ws = null
const listeners = new Set()

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
      } else {
        store.report = event.content
        store.reportDone = event.done
      }
      break
    case 'chat':
      pushChat(event.agent, event)
      break
    case 'session_snapshot':
      store.sessionId = event.session_id
      store.weights = event.weights || {}
      store.excludedTools = event.excluded_tools || []
      store.valueOverrides = event.overrides || {}
      emit(event)
      break
    case 'report_summary':
      store.summaries[event.kind] = event
      break
    case 'prompt_save_strategy':
      store.savePrompt = { interventions: event.interventions, context: event.context }
      break
    case 'tool_confirm_request':
      store.confirmQueue.push(event)
      break
    case 'report_review_request':
      store.reportReviewPending = true
      break
    case 'confirm_queue_clear':
      store.confirmQueue.length = 0
      store.reportReviewPending = false
      break
    case 'templates':
      store.templates = event.templates
      break
    case 'skills':
      store.skills = event.skills
      store.defaultSkill = event.default_skill
      emit(event)
      break
    case 'strategy_saved':
      store.strategies.push(event.strategy)
      break
    case 'replay_compare':
      store.compare = event
      break
  }
}

export function connect() {
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
  send({ type: 'start_diagnosis', ...LINES[store.selectedLine] })
}

export function saveStrategy() {
  send({ type: 'save_strategy' })
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

export const listTemplates = () => send({ type: 'list_templates' })
export const activateTemplate = (name) => send({ type: 'activate_template', name })
export const deleteTemplate = (name) => send({ type: 'delete_template', name })
export const listSkills = () => send({ type: 'list_skills' })
export const activateSkill = (name) => send({ type: 'activate_skill', name })
export const resetSkills = () => send({ type: 'reset_skills' })
export const sendToolConfirm = (tool, decision, value) =>
  send({ type: 'tool_confirm_response', tool, decision, value })
export const sendReportReview = (satisfied, instruction) =>
  send({ type: 'report_review_response', satisfied, instruction })
export const respondSavePrompt = (save) =>
  send({ type: 'save_prompt_response', save })
