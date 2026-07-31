"""strategy_builder：确定性构建完整自包含 Skill Markdown。"""
import strategy_builder

BASE = """---
name: comprehensive_diagnosis
description: base
---

# 输电线路综合诊断

```yaml
weights:
  LightningDiagnosisTool: 1.0
  IcingDiagnosisTool: 0.9
```

## 工具调用策略

| Tool | Weight | Call Condition |
|------|--------|---------------|
| LightningDiagnosisTool | 1.0 | Always call |
| IcingDiagnosisTool | 0.9 | Call when temp <= 5C |
"""


def _base_dir(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    (d / "comprehensive_diagnosis.md").write_text(BASE, encoding="utf-8")
    return d


def _config(**over):
    cfg = {
        "name": "夏季策略",
        "line_context": "500kV雅湖线",
        "weights": {"LightningDiagnosisTool": 0.5, "IcingDiagnosisTool": 0.9},
        "excluded_tools": ["IcingDiagnosisTool"],
        "template_name": "",
        "commander_rules": ["雷电诊断必须结合地形数据"],
        "report_modifications": ["删除第三章"],
        "custom_data": ["将LightningDiagnosisTool相关数值修正为雷电流 28kA"],
        "trail": [{"kind": "override", "tool": "LightningDiagnosisTool", "value": "雷电流 28kA", "text": ""},
                  {"kind": "exclude", "tool": "IcingDiagnosisTool", "value": None, "text": ""}],
    }
    cfg.update(over)
    return cfg


def test_frontmatter_and_base_body(tmp_path):
    md = strategy_builder.build_skill_markdown(_config(), skills_dir=_base_dir(tmp_path))
    assert md.startswith("---\nname: 夏季策略")
    assert "500kV雅湖线" in md
    assert "# 输电线路综合诊断" in md  # 基线正文保留


def test_weights_block_updated(tmp_path):
    md = strategy_builder.build_skill_markdown(_config(), skills_dir=_base_dir(tmp_path))
    assert "LightningDiagnosisTool: 0.5" in md
    assert "weights:" in md


def test_excluded_tool_marked_skip(tmp_path):
    md = strategy_builder.build_skill_markdown(_config(), skills_dir=_base_dir(tmp_path))
    assert "**SKIP — excluded by user preference**" in md
    assert "**SKIP IcingDiagnosisTool entirely**" in md


def test_personalized_sections(tmp_path):
    md = strategy_builder.build_skill_markdown(_config(), skills_dir=_base_dir(tmp_path))
    assert "## 司令决策规则（必须遵循）" in md and "雷电诊断必须结合地形数据" in md
    assert "## 报告撰写规则（必须遵循）" in md and "删除第三章" in md
    assert "## 用户自定义数据记录" in md and "雷电流 28kA" in md
    assert "## 参数修改记录（已烘入，激活即生效）" in md


def test_weight_change_listed(tmp_path):
    md = strategy_builder.build_skill_markdown(_config(), skills_dir=_base_dir(tmp_path))
    assert "override default 1.0" in md  # 0.5 vs 默认 1.0


def test_missing_base_returns_empty_body(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    md = strategy_builder.build_skill_markdown(_config(), skills_dir=d)
    assert md.startswith("---\nname: 夏季策略")  # 不崩溃
