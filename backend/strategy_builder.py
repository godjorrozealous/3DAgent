"""策略技能构建器：代码层确定性构建完整自包含 Skill Markdown。

对齐旧项目 Cluade_PLDiagonsis-mcp-version save_skill.py 的逻辑：
基线 comprehensive_diagnosis.md 全文 + frontmatter + weights 更新
+ 排除工具 SKIP 标记 + 个性化章节（司令决策规则/报告撰写规则/参数修改/自定义数据）。
"""
import re
from datetime import datetime
from pathlib import Path

SKILLS_DIR = Path(__file__).parent / "skills"
BASE_SKILL_NAME = "comprehensive_diagnosis"
FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

DEFAULT_WEIGHTS = {
    "LightningDiagnosisTool": 1.0,
    "IcingDiagnosisTool": 0.9,
    "WindDiagnosisTool": 0.8,
    "BirdDamageDiagnosisTool": 0.6,
}


def build_skill_markdown(config: dict, skills_dir: Path = SKILLS_DIR) -> str:
    frontmatter = _build_frontmatter(config["name"], config.get("line_context") or "transmission lines")
    body = _load_base_body(skills_dir)
    body = _mark_excluded(body, config.get("excluded_tools") or [])
    body = _update_weights(body, config.get("weights") or {})
    return f"{frontmatter}\n\n{body}\n\n{_build_personalized(config)}"


def _build_frontmatter(name: str, line: str) -> str:
    return f"""---
name: {name}
description: |
  USE THIS SKILL when diagnosing power transmission line faults for {line}.
  ALWAYS activate when the input contains line name "{line}" combined with
  fault/trip/abnormal/flashover/ground/short-circuit keywords.
  Applies to 220kV/500kV/750kV/1000kV transmission lines.
  DO NOT use for distribution lines (below 110kV) or non-power-system diagnostics.
---"""


def _load_base_body(skills_dir: Path) -> str:
    path = skills_dir / f"{BASE_SKILL_NAME}.md"
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8")
    m = FRONTMATTER_PATTERN.match(content)
    return content[m.end():].strip() if m else content.strip()


def _mark_excluded(body: str, excluded: list) -> str:
    for tool in excluded:
        pattern = rf"(\|\s*\*?{re.escape(tool)}\*?\s*\|[^|]+\|)([^|]*)\|"
        body = re.sub(pattern, rf"\1 **SKIP — excluded by user preference** |", body)
    return body


def _update_weights(body: str, weights: dict) -> str:
    if not weights:
        return body
    lines = "\n".join(f"  {t}: {w}" for t, w in weights.items())
    return re.sub(r"```yaml\s*\nweights:.*?```",
                  f"```yaml\nweights:\n{lines}\n```", body, flags=re.DOTALL)


def _build_personalized(config: dict) -> str:
    sections = ["# 基于本次诊断会话的个性化优化\n"]
    excluded = config.get("excluded_tools") or []
    if excluded:
        sections.append("## 排除的工具\n")
        for t in excluded:
            sections.append(f"- **SKIP {t} entirely** — do not include it in the diagnosis plan or report.")
        sections.append("")
    changes = [(t, w) for t, w in (config.get("weights") or {}).items()
               if t in DEFAULT_WEIGHTS and float(w) != DEFAULT_WEIGHTS[t]]
    if changes:
        sections.append("## 权重调整\n")
        for t, w in changes:
            sections.append(f"- {t}: use weight {w} (override default {DEFAULT_WEIGHTS[t]})")
        sections.append("")
    rules = config.get("commander_rules") or []
    if rules:
        sections.append("## 司令决策规则（必须遵循）\n")
        sections.append("When planning and orchestrating the diagnosis, the commander MUST apply these rules:")
        for r in rules:
            sections.append(f"- **{r}**")
        sections.append("")
    mods = config.get("report_modifications") or []
    if mods:
        sections.append("## 报告撰写规则（必须遵循）\n")
        sections.append("When composing the report, apply the following rules IN ADDITION to the standard template structure:")
        for r in mods:
            sections.append(f"- **{r}**")
        sections.append("")
    trail = [t for t in (config.get("trail") or [])
             if t.get("kind") in ("override", "time_range", "external_data")]
    if trail:
        sections.append("## 参数修改记录（已烘入，激活即生效）\n")
        for t in trail:
            sections.append(f"- {t.get('kind')}: {t.get('tool', '')} -> {t.get('value')}")
        sections.append("")
    custom = config.get("custom_data") or []
    if custom:
        sections.append("## 用户自定义数据记录\n")
        for c in custom:
            sections.append(f"- {c}")
        sections.append("")
    if config.get("template_name"):
        sections.append("## 模板引用\n")
        sections.append(f"- Use template **{config['template_name']}** as the report structure guide.")
        sections.append("")
    sections.append(f"---\n\n*Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    return "\n".join(sections)
