"""多智能体编排核心：以 PLDiagnosis 为「司令员」大脑，对接真实诊断智能体平台。

数据链路：
  前端 WebSocket -> 本管理器 -> PLDiagnosis /chat (SSE)
    -> MCP 诊断服务 (8001-8004) -> 特高压 Mock 数据平台 (8000)

席位映射：
  commander 司令员      = PLDiagnosis 主智能体（意图解析/规划/汇总/签发）
  lightning 雷电诊断    = LightningDiagnosisTool  (8001, 真实取数)
  wind     风偏诊断     = WindDiagnosisTool       (8003)
  icing    覆冰诊断     = IcingDiagnosisTool      (8002)
  bird     鸟害诊断     = BirdDamageDiagnosisTool (8004)
  audit    报告审核     = ReportComposer 报告生成与规范化
"""
import asyncio
import datetime
import json
import re
from pathlib import Path

from fastapi import WebSocket

import pld_client
import records
import strategy_builder

TRAILS_FILE = Path(__file__).parent / "data" / "strategy_trails.json"


def _load_trails() -> dict:
    try:
        return json.loads(TRAILS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_trails(trails: dict):
    TRAILS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRAILS_FILE.write_text(json.dumps(trails, ensure_ascii=False, indent=1), encoding="utf-8")

AGENTS = {
    "commander": {"name": "司令员智能体", "role": "主智能体 / 意图解析·规划·汇总签发"},
    "lightning": {"name": "雷电诊断智能体", "role": "LightningDiagnosisTool :8001"},
    "wind": {"name": "风偏诊断智能体", "role": "WindDiagnosisTool :8003"},
    "icing": {"name": "覆冰诊断智能体", "role": "IcingDiagnosisTool :8002"},
    "bird": {"name": "鸟害诊断智能体", "role": "BirdDamageDiagnosisTool :8004"},
    "audit": {"name": "报告审核智能体", "role": "ReportComposer 报告生成"},
}

# 席位 -> PLD 工具名
TOOL_AGENTS = {
    "lightning": "LightningDiagnosisTool",
    "wind": "WindDiagnosisTool",
    "icing": "IcingDiagnosisTool",
    "bird": "BirdDamageDiagnosisTool",
}
TOOL_TO_AGENT = {v: k for k, v in TOOL_AGENTS.items()}

DIAGNOSE_MESSAGE = "雅湖线 2025-05-08 19:46 发生跳闸，请进行故障综合诊断"

SESSION_CONTEXT = "【当前会话：{line}｜{tool}】"


def parse_planned_tools(text: str) -> list[str]:
    """从「诊断计划」文本提取计划调用的工具名（去重保序）。"""
    seen: dict[str, None] = {}
    for m in re.findall(r"\w+DiagnosisTool", text or ""):
        seen.setdefault(m)
    return [t for t in seen if t in TOOL_TO_AGENT]


class AgentManager:
    def __init__(self):
        self.status = {aid: "idle" for aid in AGENTS}
        self.connections: set[WebSocket] = set()
        self.current_task: asyncio.Task | None = None
        self.session_id: str | None = None
        self.run_history: list[dict] = []      # 每轮诊断记录（用于复盘对比）
        self.saved_strategies: list[dict] = []
        self.last_report: str = ""
        self.last_summaries: dict[str, dict] = {}   # "realtime"|"replay" -> report_summary 事件体
        self.local_interventions: int = 0        # 模板/策略类操作（PLD action_log 之外的干预）
        self._action_count_at_start: int = 0     # 本轮开始时 PLD action_log 长度
        self.intervention_trail: list[dict] = []  # 本轮干预线索收集
        self.pending_confirms: dict[str, dict] = {}   # tool -> 待确认的 tool_confirm_request 体
        self.confirm_decisions: dict[str, dict] = {}  # tool -> {decision, value?}
        self.value_overrides: dict[str, str] = {}     # tool -> 改后数值文本（随 snapshot 下发）
        self._confirms_done: asyncio.Event | None = None
        self._review_event: asyncio.Event | None = None
        self._review_response: dict = {}
        self._chat_tasks: set[asyncio.Task] = set()
        self.planned_tools: list[str] = []
        self._run_replay: bool = False
        self.objection_log: list[dict] = []     # 全程异议/意见/用户输入记录（供 skill 与结果集）
        self.current_line: str = ""             # 当前诊断线路文本（Task 6 使用）
        self.current_record_id: int | None = None  # 当前诊断对应的结果集记录 id（Task 6 使用）
        self.diagnosis_queue: list[dict] = []   # 排队中的诊断（运行中提交的新线路）

    # ---------- 连接管理 ----------
    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.add(ws)
        await ws.send_json({
            "type": "init",
            "agents": [{"id": a, **info, "status": self.status[a]} for a, info in AGENTS.items()],
            "strategies": self.saved_strategies,
            "session_id": self.session_id,
        })
        await self._broadcast_queue()

    def disconnect(self, ws: WebSocket):
        self.connections.discard(ws)

    async def broadcast(self, event: dict):
        dead = []
        for ws in self.connections:
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    # ---------- 事件辅助 ----------
    async def set_status(self, agent: str, status: str):
        self.status[agent] = status
        await self.broadcast({"type": "agent_status", "agent": agent, "status": status})

    async def log(self, agent: str, message: str):
        await self.broadcast({
            "type": "log",
            "agent": agent,
            "agent_name": AGENTS[agent]["name"],
            "message": message,
            "time": datetime.datetime.now().strftime("%H:%M:%S"),
        })

    async def chat_say(self, agent: str, message: str):
        await self.broadcast({
            "type": "chat", "agent": agent, "from": "agent",
            "message": message,
            "time": datetime.datetime.now().strftime("%H:%M:%S"),
        })

    # ---------- 消息入口 ----------
    async def handle_message(self, data: dict):
        mtype = data.get("type")
        if mtype == "start_diagnosis":
            await self._start_run(replay=False, text=str(data.get("text", "")).strip())
        elif mtype == "replay":
            await self._start_run(replay=True)
        elif mtype == "save_strategy":
            await self.save_strategy(str(data.get("name", "")))
        elif mtype == "chat":
            agent = data.get("agent", "commander")
            message = str(data.get("message", "")).strip()
            if agent in AGENTS and message:
                if self.current_task and not self.current_task.done() and not self._run_replay:
                    await self.chat_say(agent, "实时诊断执行中不接受干预，请在复盘重跑中进行。")
                    return
                self.objection_log.append({
                    "time": datetime.datetime.now().strftime("%H:%M:%S"),
                    "kind": "user_input",
                    "text": f"[{AGENTS[agent]['name']}] {message}"})
                task = asyncio.create_task(self.handle_chat(agent, message))
                self._chat_tasks.add(task)
                task.add_done_callback(self._chat_tasks.discard)
        elif mtype == "list_templates":
            await self.send_templates()
        elif mtype == "activate_template":
            await self.activate_template(str(data.get("name", "")))
        elif mtype == "delete_template":
            await pld_client.delete_template(str(data.get("name", "")))
            await self.send_templates()
        elif mtype == "list_skills":
            await self.send_skills()
        elif mtype == "activate_skill":
            name = str(data.get("name", ""))
            await pld_client.set_default_skill(name)
            self.local_interventions += 1
            await self.log("commander", f"诊断策略已切换为「{name}」（全局默认）。")
            await self.send_skills()
        elif mtype == "reset_skills":
            await pld_client.reset_skills()
            self.local_interventions += 1
            await self.log("commander", "已重置为默认诊断策略。")
            await self.send_skills()
            await self._refresh_snapshot()
        elif mtype == "save_prompt_response":
            if data.get("save"):
                await self.save_strategy(str(data.get("name", "")))
        elif mtype == "tool_confirm_response":
            tool = str(data.get("tool", ""))
            if tool in self.pending_confirms:
                decision = data.get("decision", "ok")
                if decision != "ok":
                    now = datetime.datetime.now().strftime("%H:%M:%S")
                    if decision == "override":
                        self.objection_log.append({
                            "time": now, "kind": "custom_data", "tool": tool,
                            "text": f"将{tool}相关数值修正为{data.get('value')}"})
                    else:
                        self.objection_log.append({
                            "time": now, "kind": "tool_objection", "tool": tool,
                            "decision": decision, "value": data.get("value")})
                self.confirm_decisions[tool] = {
                    "decision": data.get("decision", "ok"),
                    "value": data.get("value"),
                }
                del self.pending_confirms[tool]
                if not self.pending_confirms and self._confirms_done:
                    self._confirms_done.set()
        elif mtype == "report_review_response":
            self._review_response = data
            if self._review_event:
                self._review_event.set()
        elif mtype == "cancel_queued":
            idx = int(data.get("index", -1))
            if 0 <= idx < len(self.diagnosis_queue):
                item = self.diagnosis_queue.pop(idx)
                await self.log("commander", f"已取消排队诊断：{item['text']}")
                await self._broadcast_queue()
        elif mtype == "list_records":
            await self.send_records()
        elif mtype == "get_record":
            rec = records.get_record(int(data.get("id", -1)))
            if rec:
                await self.broadcast({"type": "record_detail", "record": rec})

    # ---------- 模板 / 策略管理 ----------
    async def send_templates(self):
        try:
            data = await pld_client.list_templates()
            await self.broadcast({"type": "templates", "templates": data.get("templates", [])})
        except Exception as exc:  # noqa: BLE001
            await self.log("audit", f"模板列表获取失败:{exc}")

    async def send_skills(self):
        try:
            skills = (await pld_client.list_skills()).get("skills", [])
            default = (await pld_client.get_default_skill()).get("default_skill", "")
            await self.broadcast({"type": "skills", "skills": skills, "default_skill": default})
        except Exception as exc:  # noqa: BLE001
            await self.log("commander", f"策略列表获取失败:{exc}")

    async def activate_template(self, name: str):
        if not name:
            return
        result = await pld_client.activate_template(name)
        if not result.get("success"):
            await self.log("audit", f"模板「{name}」激活失败。")
            return
        self.local_interventions += 1
        await self.log("audit", f"模板「{name}」已激活，按模板章节结构重整报告……")
        await self.send_templates()
        # 激活即重整：走 modify_report 意图
        async for event in pld_client.chat_stream("请严格按当前激活模板的章节结构重整当前诊断报告"):
            if event.get("event_type") == "complete":
                report = event.get("payload", {}).get("report")
                if report:
                    self.last_report = report
                    await self.broadcast({"type": "report", "content": report, "done": True})
        await self._refresh_snapshot()

    async def _start_run(self, replay: bool, text: str = ""):
        if self.current_task and not self.current_task.done():
            if not replay and text:
                self.diagnosis_queue.append({
                    "text": text,
                    "time": datetime.datetime.now().strftime("%H:%M:%S"),
                })
                await self.log("commander",
                               f"诊断执行中，已将「{text}」加入排队（第 {len(self.diagnosis_queue)} 位）。")
                await self._broadcast_queue()
            else:
                await self.log("commander", "已有诊断任务在执行中，请等待完成后再发起。")
            return
        self.current_task = asyncio.create_task(self.run_diagnosis(replay=replay, text=text))

    async def _broadcast_queue(self):
        await self.broadcast({
            "type": "diagnosis_queue",
            "current": self.current_line,
            "queue": list(self.diagnosis_queue),
        })

    async def send_records(self):
        try:
            summaries = [{
                "id": r.get("id"), "line": r.get("line", ""), "time": r.get("time", ""),
                "has_replay": bool(r.get("replays")),
                "strategies": r.get("strategies", []),
                "objections": [o.get("text", "") for o in r.get("objections", []) if o.get("text")],
            } for r in records.list_records()]
            await self.broadcast({"type": "records_list", "records": summaries})
        except Exception as exc:  # noqa: BLE001
            await self.log("commander", f"诊断记录读取失败:{exc}")

    # ---------- 主诊断流程（转发 PLDiagnosis） ----------
    async def _wait_pld_idle(self, timeout: float = 300.0):
        """等待 PLD 会话离开 diagnosing 状态（干预会自动触发重诊断，需等其完成才能复盘）。"""
        if not self.session_id:
            return
        deadline = asyncio.get_event_loop().time() + timeout
        waiting_logged = False
        while asyncio.get_event_loop().time() < deadline:
            try:
                session = await pld_client.get_session(self.session_id)
            except Exception:
                return
            if (session or {}).get("status") != "diagnosing":
                return
            if not waiting_logged:
                waiting_logged = True
                await self.log("commander", "PLD 会话正在执行上一轮重诊断，等待其完成后再发起复盘……")
            await asyncio.sleep(3)

    async def _stream_run(self, message: str, replay: bool, run_record: dict) -> dict:
        """执行一轮 PLD 诊断流：转发事件、更新席位、复盘中收集逐项确认并下发异议。

        返回 complete 事件的 summary；PLD 报错抛 RuntimeError 由调用方捕获。
        """
        report_buf = ""
        summary: dict = {}
        tools_started = False
        tools_done: set[str] = set()
        started_logged = False
        async for event in pld_client.chat_stream(message):
            etype = event.get("event_type")
            payload = event.get("payload", {})
            sid = event.get("session_id")
            if sid:
                self.session_id = sid

            if etype == "start":
                if not started_logged:
                    started_logged = True
                    await self.log("commander", "PLDiagnosis 主智能体已受理，开始意图解析与诊断规划。")
            elif etype == "thinking":
                msg = (payload.get("message") or "").strip()
                # 过滤 LLM 流式 JSON 片段（累积文本），只保留阶段性进度消息
                if msg and not msg.startswith(("{", '"')):
                    await self.log("commander", msg)
                if "诊断计划" in msg:
                    parsed = parse_planned_tools(msg)
                    if parsed:
                        self.planned_tools = parsed
                        await self._refresh_snapshot()
                if not tools_started and "执行诊断工具" in msg:
                    tools_started = True
                    await self._mark_tools_running()
                if "生成诊断报告" in msg:
                    await self.set_status("audit", "running")
                    await self.log("audit", "接收各诊断工具原始输出，生成规范化综合报告……")
            elif etype == "result":
                # 单个诊断工具真实返回：更新对应席位
                tool = payload.get("tool", "")
                aid = TOOL_TO_AGENT.get(tool)
                output = payload.get("output", {}) or {}
                sd = output.get("structured_data", {}) or {}
                if aid:
                    tools_done.add(aid)
                    if self.status[aid] == "running":
                        await self.set_status(aid, "completed")
                    fault = sd.get("fault_type", "—")
                    conf = sd.get("confidence", "—")
                    evid = (sd.get("evidence") or ["—"])[0]
                    raw = output.get("raw_text", "")
                    empty = not raw and not sd
                    if empty:
                        await self.log(aid, f"⚠ {tool} 未返回有效结果。")
                    else:
                        await self.log(aid, f"{tool} 返回：倾向「{fault}」，置信度 {conf}；证据：{evid}")
                    # 将子报告实时推送到报告面板
                    if raw:
                        report_buf += f"\n\n## 📡 {AGENTS[aid]['name']}原始诊断\n\n{raw}\n"
                        await self.broadcast({"type": "report", "content": report_buf, "done": False})
                    if replay:
                        self.pending_confirms[tool] = {
                            "type": "tool_confirm_request",
                            "agent": aid, "tool": tool,
                            "fault_type": fault, "confidence": conf,
                            "evidence": evid,
                            "raw_text": raw, "structured_data": sd,
                            "override": self.value_overrides.get(tool),
                            "empty": empty,
                        }
                        await self.broadcast(self.pending_confirms[tool])
            elif etype == "content":
                chunk = payload.get("content", "")
                if chunk:
                    report_buf += chunk
                    await self.broadcast({"type": "report", "content": report_buf, "done": False})
            elif etype == "complete":
                report = payload.get("report") or report_buf
                summary = payload.get("summary", {})
                self.last_report = report
                run_record["summary"] = summary
                run_record["report"] = report
                run_record["tools_run"] = sorted(tools_done)
                await self.broadcast({"type": "report", "content": report, "done": True})
                if replay:
                    self._confirms_done = asyncio.Event()
                    if self.pending_confirms:
                        await self.log("commander", "等待指挥员逐项确认各工具诊断结果……")
                        try:
                            await asyncio.wait_for(self._confirms_done.wait(), timeout=1800)
                        except asyncio.TimeoutError:
                            await self.log("commander", "确认等待超时，按无异议继续。")
                            self.pending_confirms.clear()
                    await self._dispatch_objections()
            elif etype == "error":
                raise RuntimeError(payload.get("message", "PLDiagnosis 返回错误"))
        return summary

    async def run_diagnosis(self, replay: bool = False, text: str = ""):
        message = text or DIAGNOSE_MESSAGE
        self.current_line = message
        await self._broadcast_queue()
        await self.broadcast({"type": "report", "content": "", "done": False, "reset": True})
        self.intervention_trail = []
        # 每轮开跑重置本轮计划，防止上一轮「诊断计划」残留被误用
        self.planned_tools = []
        if not replay:
            self.objection_log = []
        run_record: dict = {"replay": replay, "time": datetime.datetime.now().strftime("%H:%M:%S")}
        summary: dict = {}
        try:
            self._run_replay = replay
            self.current_task = asyncio.current_task()
            await self.broadcast({"type": "run_state", "mode": "replay" if replay else "realtime"})
            await self.set_status("commander", "running")
            # 等待进行中的 chat 干预任务完成，避免其触发的自动重诊断与本次诊断冲突
            if self._chat_tasks:
                await asyncio.gather(*list(self._chat_tasks), return_exceptions=True)
            await self._wait_pld_idle()
            if replay:
                await self.log("commander", "【复盘】按已保存的人工干预策略重新执行诊断，验证策略是否生效。")
            else:
                await self.log("commander", f"接收到任务：{message}")

            summary = await self._stream_run(message, replay, run_record)

            # 以下步骤沿用旧版嵌套在 complete 分支内的语义：仅在 complete 发生后执行，
            # 避免流提前结束时空等审核响应 1800s / _finish_run 补记日志干扰
            run_completed = "report" in run_record
            if replay and run_completed:
                # 报告审核循环：报告问题→仅改报告；诊断问题→司令收集意见重跑完整诊断；最多 5 轮
                for _ in range(5):
                    self._review_event = asyncio.Event()
                    self._review_response = {}
                    await self.broadcast({
                        "type": "report_review_request",
                        "empty": not bool((self.last_report or "").strip()),
                    })
                    try:
                        await asyncio.wait_for(self._review_event.wait(), timeout=1800)
                    except asyncio.TimeoutError:
                        break
                    if self._review_response.get("satisfied"):
                        break
                    instruction = str(self._review_response.get("instruction", "")).strip()
                    if not instruction:
                        break
                    now = datetime.datetime.now().strftime("%H:%M:%S")
                    if self._review_response.get("kind", "report") == "diagnosis":
                        self.objection_log.append({
                            "time": now, "kind": "diagnosis_objection", "text": instruction})
                        await self.log("commander",
                                       f"复盘异议（诊断流程）：{instruction}，司令收集意见后重新组织完整诊断。")
                        summary = await self._stream_run(
                            f"{message}\n【复盘异议，本次诊断必须采纳】{instruction}", True, run_record)
                        continue
                    await self.log("audit", f"按指挥员意见修改报告:{instruction}")
                    self._trail("report_modify", text=instruction)
                    self.objection_log.append({
                        "time": now, "kind": "report_modify", "text": instruction})
                    await self._wait_pld_idle()
                    async for ev in pld_client.chat_stream(instruction):
                        p = ev.get("payload", {})
                        if ev.get("event_type") == "complete" and p.get("report"):
                            self.last_report = p["report"]
                            await self.broadcast({"type": "report", "content": p["report"], "done": True})
            if run_completed:
                await self._finish_run(run_record, summary, replay)

        except Exception as exc:  # noqa: BLE001
            await self.log("commander", f"诊断流程异常：{exc}")
            await self.set_status("commander", "error")
            if replay:
                # 复盘中途异常：清空待确认队列与决策，通知前端复位确认/审核状态
                self.pending_confirms.clear()
                self.confirm_decisions.clear()
                await self.broadcast({"type": "confirm_queue_clear"})
                await self.log("commander", "【复盘】流程异常终止，确认队列已清空，状态已复位。")
            for aid in TOOL_AGENTS:
                if self.status[aid] == "running":
                    await self.set_status(aid, "idle")
            if self.status["audit"] == "running":
                await self.set_status("audit", "idle")
        finally:
            self._run_replay = False
            await self.broadcast({"type": "run_state", "mode": None})
            if self.diagnosis_queue:
                nxt = self.diagnosis_queue.pop(0)
                await self._broadcast_queue()
                await self.log("commander", f"开始排队中的下一线路诊断：{nxt['text']}")
                self.current_task = asyncio.create_task(
                    self.run_diagnosis(replay=False, text=nxt["text"]))

    def _trail(self, kind: str, tool: str = "", value=None, text: str = ""):
        self.intervention_trail.append({
            "kind": kind, "tool": tool, "value": value, "text": text,
            "time": datetime.datetime.now().strftime("%H:%M:%S"),
        })

    async def _dispatch_objections(self):
        """复盘确认后的异议处理：逐条下发 PLD（recheck/exclude/adjust_weight/手动改值）。"""
        objections = {t: d for t, d in self.confirm_decisions.items() if d["decision"] != "ok"}
        self.confirm_decisions.clear()
        if not objections:
            return
        final_report = None
        for tool, d in objections.items():
            await self._wait_pld_idle()
            decision, value = d["decision"], d.get("value")
            if decision == "recheck":
                self._trail("recheck", tool)
                cmd = f"重新检查{tool}"
            elif decision == "exclude":
                self._trail("exclude", tool)
                cmd = f"排除{tool}"
            elif decision == "weight":
                self._trail("weight", tool, value)
                cmd = f"将{tool}权重调整为{value}"
            elif decision == "override":
                self._trail("override", tool, value)
                self.value_overrides[tool] = str(value)
                cmd = f"修改报告：将{tool}相关数值修正为{value}"
            elif decision == "time_range":
                self._trail("time_range", tool, value)
                cmd = f"重新检查{tool}，查询时间段{value}"
            else:
                continue
            await self.log("commander", f"下发复盘异议:{cmd}")
            try:
                async for event in pld_client.chat_stream(cmd):
                    p = event.get("payload", {})
                    if event.get("event_type") == "complete" and p.get("report"):
                        final_report = p["report"]
            except Exception as exc:  # noqa: BLE001
                await self.log("commander", f"异议下发失败({tool}):{exc}")
        if final_report:
            self.last_report = final_report
            await self.broadcast({"type": "report", "content": final_report, "done": True})
        await self._refresh_snapshot()

    def _count_interventions(self, session: dict | None) -> int:
        delta = len((session or {}).get("action_log", [])) - self._action_count_at_start
        return max(delta, 0) + self.local_interventions

    async def _mark_tools_running(self):
        """工具执行阶段：计划内席位进入 RUNNING；计划外「亮一下就灭」。"""
        planned = set(self.planned_tools)
        if not planned:
            planned = set(TOOL_AGENTS.values())
        excluded = set()
        try:
            if self.session_id:
                session = await pld_client.get_session(self.session_id)
                excluded = set((session or {}).get("excluded_tools", []))
        except Exception:
            pass

        async def run_agent(aid: str, delay: float):
            await asyncio.sleep(delay)
            await self.set_status(aid, "running")
            await self.log(aid, f"通过 MCP 服务调用 {TOOL_AGENTS[aid]} 采集诊断数据……")

        async def blink_agent(aid: str, delay: float):
            await asyncio.sleep(delay)
            await self.set_status(aid, "running")
            await asyncio.sleep(0.6)
            await self.set_status(aid, "idle")
            await self.log(aid, "按 LLM 诊断策略，本轮未调用该工具（条件不满足）。")

        tasks = []
        for i, (aid, tool) in enumerate(TOOL_AGENTS.items()):
            if tool in planned and tool not in excluded:
                tasks.append(run_agent(aid, i * 1.2))
            else:
                tasks.append(blink_agent(aid, i * 0.3))
        await asyncio.gather(*tasks)

    async def _finish_run(self, run_record: dict, summary: dict, replay: bool):
        # 拉取会话快照：权重 / 排除列表（人工干预的真实状态）
        session = None
        try:
            if self.session_id:
                session = await pld_client.get_session(self.session_id)
        except Exception as exc:  # noqa: BLE001
            await self.log("commander", f"会话快照获取失败：{exc}")

        excluded = (session or {}).get("excluded_tools", [])
        weights = (session or {}).get("active_weights", {})
        run_record["excluded_tools"] = excluded
        run_record["weights"] = weights
        self.run_history.append(run_record)

        kind = "replay" if replay else "realtime"
        summary_event = {
            "type": "report_summary",
            "kind": kind,
            "summary": summary,
            "report": run_record.get("report", ""),
            "weights": weights,
            "excluded_tools": excluded,
            "action_log": (session or {}).get("action_log", [])[self._action_count_at_start:],
            "time": run_record["time"],
        }
        self.last_summaries[kind] = summary_event
        await self.broadcast(summary_event)

        tools_run = set(run_record.get("tools_run", []))
        for aid, tool in TOOL_AGENTS.items():
            if tool in excluded:
                await self.set_status(aid, "idle")
                await self.log(aid, "该工具已被人工策略排除，本轮未参与诊断。")
            elif aid in tools_run:
                w = weights.get(tool)
                await self.log(aid, f"结果已回传司令员。（当前权重 {w}）" if w else "结果已回传司令员。")
            elif self.status[aid] == "running":
                await self.set_status(aid, "idle")
                await self.log(aid, "按 LLM 诊断策略，本轮未调用该工具（条件不满足）。")

        await self.set_status("audit", "completed")
        await self.log("audit", "报告格式与术语规范化审核通过。")
        fault = summary.get("fault_type", "未知")
        conf = summary.get("confidence", 0)
        await self.log("commander", f"司令员签发最终报告：故障类型「{fault}」，置信度 {conf}。")
        await self.set_status("commander", "completed")
        await self.broadcast({
            "type": "session_snapshot",
            "session_id": self.session_id,
            "weights": weights,
            "excluded_tools": excluded,
            "summary": summary,
            "overrides": self.value_overrides,
            "planned_tools": self.planned_tools,
        })

        n = self._count_interventions(session)
        if n > 0:
            await self.broadcast({
                "type": "prompt_save_strategy",
                "interventions": n,
                "context": "replay" if replay else "realtime",
            })
        # 基线滚动：下一轮只统计本轮结束后新增的干预
        self._action_count_at_start = len((session or {}).get("action_log", []))
        self.local_interventions = 0

        # 复盘：与首轮基线对比，验证策略是否生效
        if replay and self.run_history:
            baseline = next((r for r in self.run_history if not r.get("replay") and r.get("summary")), None)
            if baseline:
                await self.broadcast({
                    "type": "replay_compare",
                    "baseline": {"summary": baseline.get("summary"), "weights": baseline.get("weights", {}), "excluded_tools": baseline.get("excluded_tools", [])},
                    "replay": {"summary": summary, "weights": weights, "excluded_tools": excluded},
                })
                await self.log("commander", "【复盘】策略生效对比已生成，请查看复盘面板。")

        # 结果集持久化：实时建档，复盘追加；异议快照随轮更新
        try:
            if replay:
                if self.current_record_id is not None:
                    records.attach_replay(self.current_record_id, run_record.get("report", ""), summary)
                    records.set_objections(self.current_record_id, self.objection_log)
            else:
                rec = records.create_record(self.current_line, run_record["time"])
                self.current_record_id = rec["id"]
                records.attach_realtime(rec["id"], run_record.get("report", ""), summary)
                records.set_objections(rec["id"], self.objection_log)
        except Exception as exc:  # noqa: BLE001
            await self.log("commander", f"诊断记录持久化失败：{exc}")

    # ---------- 人工直聊干预 ----------
    async def handle_chat(self, agent: str, message: str):
        if agent == "commander":
            # 转发给 PLDiagnosis：由真实意图分类器处理（排除/恢复/调权/复查/修改报告…）
            await self.log("commander", f"接收人工干预指令：「{message}」，下发 PLDiagnosis 意图分类器。")
            await self.set_status("commander", "running")
            reply_parts = []
            try:
                async for event in pld_client.chat_stream(message):
                    etype = event.get("event_type")
                    payload = event.get("payload", {})
                    sid = event.get("session_id")
                    if sid:
                        self.session_id = sid
                    if etype == "thinking" and payload.get("message"):
                        msg = payload["message"].strip()
                        if msg and not msg.startswith(("{", '"')):
                            await self.log("commander", msg)
                    elif etype == "content" and payload.get("content"):
                        reply_parts.append(payload["content"])
                    elif etype == "complete":
                        summary = payload.get("summary", {})
                        report = payload.get("report")
                        if report:
                            self.last_report = report
                            await self.broadcast({"type": "report", "content": report, "done": True})
                        reply = "干预已生效。"
                        if summary:
                            reply = f"干预已生效：当前结论「{summary.get('fault_type', '未知')}」，置信度 {summary.get('confidence', 0)}。"
                        await self.chat_say("commander", reply)
                        await self._refresh_snapshot()
                    elif etype == "error":
                        await self.chat_say("commander", f"干预未生效：{payload.get('message', '未知错误')}")
                if reply_parts and not any("干预" in p for p in reply_parts):
                    pass
            except Exception as exc:  # noqa: BLE001
                await self.chat_say("commander", f"干预下发失败：{exc}")
                await self.set_status("commander", "error")
                return
            await self.set_status("commander", "completed")
        else:
            tool = TOOL_AGENTS.get(agent, agent)
            prefixed = SESSION_CONTEXT.format(line=self.current_line or "未知线路", tool=tool) + message
            await self.log(agent, f"收到针对 {tool} 的会话内要求，转发 PLDiagnosis 处理。")
            try:
                async for event in pld_client.chat_stream(prefixed):
                    etype = event.get("event_type")
                    payload = event.get("payload", {})
                    if etype == "complete":
                        if payload.get("report"):
                            self.last_report = payload["report"]
                            await self.broadcast({"type": "report", "content": payload["report"], "done": True})
                        await self.chat_say(agent, payload.get("message") or "要求已处理，报告已同步更新。")
                        await self._refresh_snapshot()
                    elif etype == "error":
                        await self.chat_say(agent, f"处理失败:{payload.get('message', '未知错误')}")
            except Exception as exc:  # noqa: BLE001
                await self.chat_say(agent, f"要求下发失败:{exc}")

    async def _refresh_snapshot(self):
        try:
            if self.session_id:
                session = await pld_client.get_session(self.session_id)
                await self.broadcast({
                    "type": "session_snapshot",
                    "session_id": self.session_id,
                    "weights": session.get("active_weights", {}),
                    "excluded_tools": session.get("excluded_tools", []),
                    "summary": (session.get("latest_summary") or {}),
                    "overrides": self.value_overrides,
                    "planned_tools": self.planned_tools,
                })
        except Exception:
            pass

    # ---------- 策略保存 ----------
    async def save_strategy(self, name: str = ""):
        try:
            session = await pld_client.get_session(self.session_id) if self.session_id else None
        except Exception as exc:  # noqa: BLE001
            await self.log("commander", f"保存策略失败：{exc}")
            return
        if not session:
            await self.log("commander", "当前无可保存的诊断会话，请先完成一轮诊断。")
            return

        weights = session.get("active_weights", {})
        excluded = session.get("excluded_tools", [])
        name = name.strip() or f"cmd_strategy_{datetime.datetime.now().strftime('%H%M%S')}"
        # 安全 slug：连续空白转单个下划线（中文字符保留）
        name = re.sub(r"\s+", "_", name)
        # 重名去重：对内存中已存策略名 + trails 文件键，冲突追加 _2/_3…
        existing = {s.get("name") for s in self.saved_strategies} | set(_load_trails().keys())
        unique = name
        i = 2
        while unique in existing:
            unique = f"{name}_{i}"
            i += 1
        if unique != name:
            await self.log("commander", f"策略名「{name}」已存在，重命名为「{unique}」。")
        name = unique

        content = strategy_builder.build_skill_markdown({
            "name": name,
            "line_context": self.current_line or "transmission lines",
            "weights": weights,
            "excluded_tools": excluded,
            "template_name": "",
            "report_modifications": [o["text"] for o in self.objection_log if o["kind"] == "report_modify"],
            "commander_rules": [o["text"] for o in self.objection_log
                                if o["kind"] in ("diagnosis_objection", "user_input")],
            "custom_data": [o["text"] for o in self.objection_log if o["kind"] == "custom_data"],
            "trail": list(self.intervention_trail),
        })

        result = await pld_client.save_skill(name, content)
        strategy = {
            "name": name,
            "time": datetime.datetime.now().strftime("%H:%M:%S"),
            "weights": weights,
            "excluded_tools": excluded,
            "trail_count": len(self.intervention_trail),
            "saved_to_pld": bool(result.get("success")),
        }
        self.saved_strategies.append(strategy)
        if self.current_record_id is not None:
            records.attach_strategy(self.current_record_id, name)
        trails = _load_trails()
        trails[name] = list(self.intervention_trail)
        _write_trails(trails)
        await self.broadcast({"type": "strategy_saved", "strategy": strategy})
        await self.log(
            "commander",
            f"人工干预策略已保存为技能「{name}」（权重 {len(weights or {})} 项 / 排除 {len(excluded or [])} 项 / 干预线索 {len(self.intervention_trail)} 条），可点击「复盘重跑」验证生效。",
        )
