import { reactive } from 'vue'

export const store = reactive({
  connected: false,
  running: false,
  agents: {},            // id -> { id, name, role, status }
  logs: [],              // 事件流
  report: '',
  reportDone: false,
  lineText: '雅湖线 2025-05-08 19:46 发生跳闸，请进行故障综合诊断',
  diagQueue: [],         // 排队中的诊断 [{ text, time }]
  currentLine: '',       // 当前执行中的诊断文本
  view: 'room',          // 'room' | 'history'
  records: [],           // 结果集列表（records_list）
  recordDetail: null,    // 结果集详情（record_detail）
  chatTarget: null,      // 双击打开直聊的智能体 id
  chatMessages: {},      // agentId -> [{ from, message, time }]
  sessionId: null,
  weights: {},           // 当前会话工具权重
  excludedTools: [],     // 当前会话排除的工具
  plannedTools: [],      // 本轮 LLM 诊断计划调用的工具（session_snapshot.planned_tools）
  strategies: [],        // 已保存的干预策略
  strategiesList: [],    // 策略管理页：PLD 技能列表
  strategiesDefault: '', // 使用中（默认）策略名
  compare: null,         // 复盘对比 { baseline, replay }
  summaries: { realtime: null, replay: null }, // 双摘要 report_summary 事件体
  templates: [],
  skills: [],
  defaultSkill: '',
  confirmQueue: [],      // tool_confirm_request 队列，响应后 shift
  agentSession: null,    // null | { agent, tool, fault_type, confidence, evidence, raw_text, structured_data, override, confirm: bool }
  agentBusy: {},         // 复盘对话异议已上报、等待重诊断结果的智能体
  replayMode: false,     // run_state.mode === 'replay'
  savePrompt: null,      // null | { interventions, items, context }
  saveNaming: null,      // null | { suggested, selected? } 命名保存弹窗
  reportReviewPending: false,
  reportReviewEmpty: false, // 复盘报告为空标记（report_review_request.empty）
  reportModal: null,     // null | { title, content, meta?: { line, faultTime } }
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

// 开发调试便利：允许在浏览器控制台/自动化中直接驱动 store
if (import.meta.env.DEV) window.__store = store
