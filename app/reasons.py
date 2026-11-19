REASONS = {"COLUMNS":"列数不符", "HEADER":"字段缺失", "MISSING":"必填值为空", "NUMBER":"数值无效", "RANGE":"超出范围", "DUPLICATE":"相同行重复", "CONFLICT":"同键数值冲突", "VERSION":"版本冲突", "EMPTY":"输入为空", "STRUCTURE":"文件结构错误",
"INSUFFICIENT_HISTORY":"有效校准历史不足", "NO_VALID_EVIDENCE":"无有效校准证据", "NEAR_TOLERANCE":"最新校准点接近容差边界", "DRIFT_MONOTONIC":"近期连续单向漂移", "FLUCTUATION_RECOVERED":"偶发波动已恢复", "EVIDENCE_EXCLUDED":"失效证据占比过高", "STABLE_EXTEND":"长期稳定延长间隔", "ROUTINE":"按基准间隔维持"}
def isolate(ctx, row, code, detail):
    ctx['quarantine'].append({**row, '原因码': code, '原因': detail})
