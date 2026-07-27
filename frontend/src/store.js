import { reactive } from 'vue'

// 真实数据平台当前仅有雅湖线一条跳闸记录（tripId: S_Y202505080552）
export const LINES = [
  { line: '±800kV 雅湖线', tower: '2025-05-08 19:46 跳闸' },
]

export const store = reactive({
  connected: false,
  running: false,
  agents: {},            // id -> { id, name, role, status }
  logs: [],              // 事件流
  report: '',
  reportDone: false,
  selectedLine: 0,
  chatTarget: null,      // 双击打开直聊的智能体 id
  chatMessages: {},      // agentId -> [{ from, message, time }]
  sessionId: null,
  weights: {},           // 当前会话工具权重
  excludedTools: [],     // 当前会话排除的工具
  strategies: [],        // 已保存的干预策略
  compare: null,         // 复盘对比 { baseline, replay }
  summaries: { realtime: null, replay: null }, // 双摘要 report_summary 事件体
  templates: [],
  skills: [],
  defaultSkill: '',
  confirmQueue: [],      // tool_confirm_request 队列，响应后 shift
  savePrompt: null,      // null | { interventions, context }
  reportReviewPending: false,
  reportModal: null,     // null | { title, content }
  compareOpen: false,
  valueOverrides: {},    // session_snapshot.overrides
})

export function pushLog(entry) {
  store.logs.push(entry)
  if (store.logs.length > 300) store.logs.splice(0, store.logs.length - 300)
}

export function pushChat(agentId, msg) {
  if (!store.chatMessages[agentId]) store.chatMessages[agentId] = []
  store.chatMessages[agentId].push(msg)
}
