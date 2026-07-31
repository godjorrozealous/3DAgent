---
name: comprehensive_diagnosis
description: |
  输电线路跳闸故障综合诊断专家。
  USE THIS SKILL when the user describes power transmission line faults,
  tripping events, line abnormalities, tower problems, lightning strikes,
  icing, wind deflection, bird damage, or any weather-related line issues.
  ALWAYS activate when the input contains line name + fault/trip/abnormal/
  flashover/ground/short-circuit keywords, even if the user does not say
  "diagnose" explicitly.
  Applies to 220kV/500kV/750kV/1000kV transmission lines.
---

# 输电线路综合诊断

## 核心算法：加权置信度

All tool results include a confidence score (0~1). Compute weighted confidence:

```
加权置信度 = tool_confidence × tool_weight
```

Sort by weighted confidence descending. The highest is the primary cause.
If the gap between top two is < 0.1, list as co-primary causes.

## 工具权重配置

```yaml
weights:
  LightningDiagnosisTool: 1.0
  IcingDiagnosisTool: 0.9
  WindDiagnosisTool: 0.8
  BirdDamageDiagnosisTool: 0.6
```

## 工具调用策略

| Tool | Weight | Call Condition |
|------|--------|---------------|
| LightningDiagnosisTool | 1.0 | Always call |
| IcingDiagnosisTool | 0.9 | Call when temp ≤ 5°C or winter; otherwise skip |
| WindDiagnosisTool | 0.8 | Always call |
| BirdDamageDiagnosisTool | 0.6 | Always call |
| WeatherDiagnosisTool | 0.5 | DO NOT call - currently disabled due to browser automation timeout |

## 诊断流程

1. **Extract info**: Parse line name, tower number, fault time (millisecond precision)
2. **Weather check**: Determine season and weather, decide if icing tool applies
3. **Parallel diagnosis**: Call all applicable tools simultaneously
4. **Weighted compute**: Calculate weighted confidence = confidence × weight for each tool
5. **Rank & judge**: Sort descending, highest is primary cause
6. **Report**: Organize output by the active template chapter structure

## 置信度等级

- HIGH: weighted confidence ≥ 0.7
- MEDIUM: weighted confidence 0.4 ~ 0.7
- LOW: weighted confidence < 0.4

## 注意事项

- Skip icing diagnosis in summer (no significance)
- Skip WeatherDiagnosisTool completely - it is currently disabled due to browser automation timeout
- Merge evidence when multiple tools point to the same fault type
- Prompt user when new tools are available
- Fault time must be millisecond-precise: YYYY-MM-DD HH:MM:SS.mmm
- Report conclusion must show weighted confidence calculation for each tool
