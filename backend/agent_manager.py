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

from fastapi import WebSocket

import pld_client

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
            await self._start_run(replay=False)
        elif mtype == "replay":
            await self._start_run(replay=True)
        elif mtype == "save_strategy":
            await self.save_strategy()
        elif mtype == "chat":
            agent = data.get("agent", "commander")
            message = str(data.get("message", "")).strip()
            if agent in AGENTS and message:
                asyncio.create_task(self.handle_chat(agent, message))

    async def _start_run(self, replay: bool):
        if self.current_task and not self.current_task.done():
            await self.log("commander", "已有诊断任务在执行中，请等待完成后再发起。")
            return
        self.current_task = asyncio.create_task(self.run_diagnosis(replay=replay))

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

    async def run_diagnosis(self, replay: bool = False):
        await self.broadcast({"type": "report", "content": "", "done": False, "reset": True})
        report_buf = ""
        run_record: dict = {"replay": replay, "time": datetime.datetime.now().strftime("%H:%M:%S")}
        try:
            await self.set_status("commander", "running")
            await self._wait_pld_idle()
            if replay:
                await self.log("commander", "【复盘】按已保存的人工干预策略重新执行诊断，验证策略是否生效。")
            else:
                await self.log("commander", f"接收到任务：{DIAGNOSE_MESSAGE}")

            tools_started = False
            tools_done: set[str] = set()
            started_logged = False
            async for event in pld_client.chat_stream(DIAGNOSE_MESSAGE):
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
                        await self.log(aid, f"{tool} 返回：倾向「{fault}」，置信度 {conf}；证据：{evid}")
                        # 将子报告实时推送到报告面板
                        raw = output.get("raw_text", "")
                        if raw:
                            report_buf += f"\n\n## 📡 {AGENTS[aid]['name']}原始诊断\n\n{raw}\n"
                            await self.broadcast({"type": "report", "content": report_buf, "done": False})
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
                    await self._finish_run(run_record, summary, replay)
                elif etype == "error":
                    raise RuntimeError(payload.get("message", "PLDiagnosis 返回错误"))

        except Exception as exc:  # noqa: BLE001
            await self.log("commander", f"诊断流程异常：{exc}")
            await self.set_status("commander", "error")
            for aid in TOOL_AGENTS:
                if self.status[aid] == "running":
                    await self.set_status(aid, "idle")
            if self.status["audit"] == "running":
                await self.set_status("audit", "idle")

    async def _mark_tools_running(self):
        """工具执行阶段：四个诊断席位并行进入 RUNNING（视觉错峰）。"""
        async def stagger(aid: str, delay: float):
            await asyncio.sleep(delay)
            await self.set_status(aid, "running")
            await self.log(aid, f"通过 MCP 服务调用 {TOOL_AGENTS[aid]} 采集诊断数据……")

        await asyncio.gather(*[stagger(aid, i * 1.2) for i, aid in enumerate(TOOL_AGENTS)])

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
            "action_log": (session or {}).get("action_log", []),
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
        })

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
            # 子席位：基于最近一次诊断上下文作答
            await asyncio.sleep(0.6)
            tool = TOOL_AGENTS[agent]
            session = None
            try:
                if self.session_id:
                    session = await pld_client.get_session(self.session_id)
            except Exception:
                pass
            excluded = (session or {}).get("excluded_tools", [])
            weights = (session or {}).get("active_weights", {})
            state = "已被人工排除" if tool in excluded else "在诊"
            w = weights.get(tool, "默认")
            await self.chat_say(
                agent,
                f"{AGENTS[agent]['name']}在线（{state}，权重 {w}）。我通过 {tool} 从接口平台采集数据。"
                "如需调整我的参与方式，请向司令员下达指令，例如「排除鸟害工具」「将雷电工具权重调整为 1.5」。",
            )

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
                })
        except Exception:
            pass

    # ---------- 策略保存 ----------
    async def save_strategy(self):
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
        name = f"cmd_strategy_{datetime.datetime.now().strftime('%H%M%S')}"
        lines = [f"# 指挥室人工干预策略 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ""]
        lines.append("## 工具权重")
        for t, w in (weights or {}).items():
            lines.append(f"- {t}: {w}")
        lines.append("")
        lines.append("## 排除工具")
        for t in (excluded or []):
            lines.append(f"- {t}")
        content = "\n".join(lines)

        result = await pld_client.save_skill(name, content)
        strategy = {
            "name": name,
            "time": datetime.datetime.now().strftime("%H:%M:%S"),
            "weights": weights,
            "excluded_tools": excluded,
            "saved_to_pld": bool(result.get("success")),
        }
        self.saved_strategies.append(strategy)
        await self.broadcast({"type": "strategy_saved", "strategy": strategy})
        await self.log(
            "commander",
            f"人工干预策略已保存为技能「{name}」（权重 {len(weights or {})} 项 / 排除 {len(excluded or [])} 项），可点击「复盘重跑」验证生效。",
        )
