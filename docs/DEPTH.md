# 深度登记 设备校准证书与测量追溯

- 规模：中型
- 使用者与工作流：检验机构质量员，合并仪器使用与校准证书，裁决测量是否在有效可追溯链内。
- 核心规则：证书有效期与量程双约束；参考标准也须在校准时有效，证书撤销向下游传播并检测环。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 证书接收 | 运行证书接收并复核证据 | `POST /api/m1`；`/work/1` | `app/modules/m1_receiving/rules.py` | `tests/test_m1.py` |
| M2 设备别名 | 运行设备别名并复核证据 | `POST /api/m2`；`/work/2` | `app/modules/m2_identity/rules.py` | `tests/test_m2.py` |
| M3 有效区间 | 运行有效区间并复核证据 | `POST /api/m3`；`/work/3` | `app/modules/m3_validity/rules.py` | `tests/test_m3.py` |
| M4 量程匹配 | 运行量程匹配并复核证据 | `POST /api/m4`；`/work/4` | `app/modules/m4_ranges/rules.py` | `tests/test_m4.py` |
| M5 溯源链路 | 运行溯源链路并复核证据 | `POST /api/m5`；`/work/5` | `app/modules/m5_trace/rules.py` | `tests/test_m5.py` |
| M6 测量裁决 | 运行测量裁决并复核证据 | `POST /api/m6`；`/work/6` | `app/modules/m6_verdict/rules.py` | `tests/test_m6.py` |
| M7 撤销复核 | 运行撤销复核并复核证据 | `POST /api/m7`；`/work/7` | `app/modules/m7_revocation/rules.py` | `tests/test_m7.py` |
| M8 间隔建议 | 运行间隔建议并复核计划与校准点 | `POST /api/m8`；`/work/8` | `app/modules/m8_interval/rules.py` | `tests/test_m8.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现会怎样 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-01 | 旧编码证书 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m1_receiving/rules.py` | `tests/test_m1.py::test_legacy_chinese` |
| TRAP-07 | 空值测量 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m2_identity/rules.py` | `tests/test_m2.py::test_missing_isolated` |
| TRAP-08 | 设备编码保形 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m2_identity/rules.py` | `tests/test_m2.py::test_device_code_preserved` |
| TRAP-14 | 定义冲突 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m2_identity/rules.py` | `tests/test_m2.py::test_conflict_certificate_flag` |
| TRAP-20 | 溯源依赖环 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m5_trace/rules.py` | `tests/test_m5.py::test_reference_cycle` |
| TRAP-22 | 设备别名 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m2_identity/rules.py` | `tests/test_m2.py::test_alias_order_independent` |
| TRAP-23 | 失效日边界 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m3_validity/rules.py` | `tests/test_m3.py::test_expiry_endpoint` |
| TRAP-25 | 多证书重叠 | 静默覆盖或误计 | 显式裁决并保留证据 | `app/modules/m3_validity/rules.py` | `tests/test_m3.py::test_overlapping_certificates` |
| TRAP-26 | 长期稳定掩盖近期漂移 | 只看长历史继续半年/一年，漏掉连续单向漂移 | 全段同号漂移与接近容差独立判定，触发即缩短到3月并给出量值依据 | `app/modules/m8_interval/rules.py` | `tests/test_m8.py::test_monotonic_drift_shortens` |
| TRAP-27 | 偶发波动误判失稳 | 只看最近几次数值导致频繁停机 | 单步大波动但已回落只维持6月，不缩短；全部非零步同号才算漂移 | `app/modules/m8_interval/rules.py` | `tests/test_m8.py::test_one_off_fluctuation_keeps_half_year` |
| TRAP-28 | 换编码/别名拆成多台 | 历史被切断，点数不足无法延长 | 复用M2并查集规范编码，旧编码记录归并到同一设备统计 | `app/modules/m8_interval/rules.py` | `tests/test_m8.py::test_renamed_device_merges_history` |
| TRAP-29 | 失效记录充当稳定证据 | 撤销/超量程/溯源中断点混入趋势计算 | 以M6裁决为采信闸门，失效点仅入明细标“否”，占比≥50%禁止延长 | `app/modules/m8_interval/rules.py` | `tests/test_m8.py::test_revoked_and_out_of_range_never_stable_evidence` |
| TRAP-30 | 重跑重复生成计划 | 同批重复提交产生重复校准计划 | 计划编号确定性派生+plans表(run_id,plan_id)主键，批次幂等复用 | `app/store.py` | `tests/test_m8.py::test_rerun_same_batch_creates_no_duplicate_plans` |

## 对账规则

输入记录 = 采信记录 + 隔离记录 + 相同行重复。重复表头与空行单独记数。业务合计按阶段中的守恒或差值列复核。运行清单有原文SHA256、规则版本与耗时；相同规则版本下同文重复提交复用批次。M8校准点守恒：每台设备观测数=采信点数+失效点数；计划数等于出现过的规范设备数，计划编号在(run_id,plan_id)维度唯一，同批重跑不新增计划行。

## 已知不覆盖

部署为本地单用户工具，不连接外部上游系统。CSV单文件5MB及一万条业务记录上限；不推断未提供的未知数据。
