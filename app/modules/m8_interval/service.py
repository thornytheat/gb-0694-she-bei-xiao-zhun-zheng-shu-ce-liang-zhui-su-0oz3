from collections import Counter
from app.modules.m8_interval import rules
from app.numeric import serial
def execute(ctx):
    before=len(ctx['quarantine'])
    result=rules.apply(ctx)
    result['stage']=8
    result['name']='间隔建议'
    result['issues']=dict(Counter(row['原因码'] for row in ctx['quarantine']))
    result['new_quarantine']=len(ctx['quarantine'])-before
    # 决策阈值随批次固化，上游重算时页面与证据都能复核采用的口径。
    ctx['manifest']['parameters'].update({
        'min_points_extend':rules.MIN_POINTS_EXTEND,
        'min_span_days_extend':rules.MIN_SPAN_DAYS_EXTEND,
        'near_limit_ratio':str(rules.NEAR_LIMIT_RATIO),
        'drift_ratio':str(rules.DRIFT_RATIO),
        'excluded_ratio_cap':str(rules.EXCLUDED_RATIO_CAP),
        'interval_ladder_months':[rules.SHORT_INTERVAL,rules.BASE_INTERVAL,rules.LONG_INTERVAL],
    })
    ctx['stages'][str(8)]=serial(result)
    return ctx
