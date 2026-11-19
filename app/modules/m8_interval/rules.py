from datetime import date, timedelta
from decimal import Decimal
import hashlib
from app.numeric import number

# 间隔阶梯（月）：长期稳定可延长，基准半年，出现风险信号缩短。
SHORT_INTERVAL = 3
BASE_INTERVAL = 6
LONG_INTERVAL = 12

# 决策阈值（随规则版本固化，写入运行清单 parameters，页面可复核）。
MIN_POINTS_EXTEND = 4          # 延长间隔所需最少有效校准点
MIN_SPAN_DAYS_EXTEND = 240     # 延长间隔所需历史跨度（约连续两个半年周期）
MIN_POINTS_RISK = 3            # 触发缩短（漂移/接近容差）所需最少有效点
NEAR_LIMIT_SPAN_V = number('20')       # 接近容差判定仅适用于全量程≤20V的仪器，避免宽量程标准源误报
NEAR_LIMIT_RATIO = number('0.1')      # 最新点距容差边界不足全量程 10% 视为接近容差
DRIFT_RATIO = number('0.1')           # 连续单向累计漂移达到全量程 10% 视为显著
EXCLUDED_RATIO_CAP = number('0.5')    # 失效证据占比达到一半时禁止延长


def add_months(day, months):
    """日历月加法：目标月没有对应日时取该月最后一天（如2/29）。"""
    month = day.month - 1 + months
    year = day.year + month // 12
    month = month % 12 + 1
    if month == 12:
        next_month_first = date(year + 1, 1, 1)
    else:
        next_month_first = date(year, month + 1, 1)
    last_day = (next_month_first - timedelta(days=1)).day
    return date(year, month, min(day.day, last_day))


def threshold_text(low, high):
    return '接近容差阈值≤' + str(NEAR_LIMIT_RATIO) + '×全量程=' + str((high - low) * NEAR_LIMIT_RATIO) + 'V'


def apply(ctx):
    # M6 裁决是采信闸门：只有“可采用”的校准点才算稳定证据。
    verdict_by_line = {r['行号']: r for r in ctx['verdicts']}
    by_device = {}
    for r in ctx['measurements']:
        verdict = verdict_by_line.get(r['行号'])
        accepted = bool(verdict and verdict['结论'] == '可采用')
        point = {
            '行号': r['行号'], '证书': r['cert'], '设备': r['canonical'],
            '校准日': r['measured_at'], '测量值_V': r['value_v'],
            '下限_V': r['min_v'], '上限_V': r['max_v'],
            '采信': accepted,
            '原因码': 'ACCEPT' if accepted else (verdict['原因码'] if verdict else 'NO_VERDICT'),
        }
        by_device.setdefault(r['canonical'], []).append(point)

    plans, point_rows, excluded_total = [], [], 0
    for device in sorted(by_device):
        points = sorted(by_device[device], key=lambda p: p['校准日'])
        good = [p for p in points if p['采信']]
        excluded = len(points) - len(good)
        excluded_total += excluded
        total_observations = len(points)

        alias_names = sorted({m['alias'] for m in ctx['measurements']
                              if m['canonical'] == device and m['alias']})
        if not good:
            last_day = max(points, key=lambda p: p['校准日'])['校准日']
            reason_code, interval = 'NO_VALID_EVIDENCE', SHORT_INTERVAL
            basis = '无可用校准点，按最短间隔管控；失效' + str(excluded) + '条（' + \
                       ','.join(sorted({p['原因码'] for p in points if not p['采信']})) + '）不作稳定证据'
        else:
            values = [number(p['测量值_V']) for p in good]
            low = number(good[-1]['下限_V'])
            high = number(good[-1]['上限_V'])
            span_v = high - low
            latest = values[-1]
            near_distance = min(latest - low, high - latest)
            # 宽量程标准源按比例判定会天然远离边界，接近容差仅对窄量程仪器生效。
            near = (len(good) >= MIN_POINTS_RISK and span_v <= NEAR_LIMIT_SPAN_V
                    and near_distance <= span_v * NEAR_LIMIT_RATIO)

            # 连续单向漂移：全部非零步同号且累计量达到全量程 10%；
            # 只要出现反向步即视为波动而非漂移，避免把偶发回落当失稳。
            deltas = [values[i] - values[i - 1] for i in range(1, len(values))]
            total_shift = values[-1] - values[0]
            signs = {1 if d > 0 else -1 for d in deltas if d != 0}
            monotonic = (len(good) >= MIN_POINTS_RISK and len(signs) == 1
                         and abs(total_shift) >= span_v * DRIFT_RATIO)

            # 偶发波动保护：任一单步跳变超过全量程 10%（随后回落、未形成连续
            # 单向漂移），不得直接延长到一年，维持半年基准间隔。
            max_abs_step = max((abs(d) for d in deltas), default=Decimal('0'))
            fluctuation = max_abs_step >= span_v * DRIFT_RATIO and not monotonic

            span_days = (date.fromisoformat(good[-1]['校准日']) -
                         date.fromisoformat(good[0]['校准日'])).days
            excluded_ratio = (Decimal(excluded) / Decimal(total_observations)
                              if total_observations else Decimal('0'))
            excluded_pct = (excluded_ratio * 100).quantize(Decimal('0.1'))
            last_day = good[-1]['校准日']

            if near or monotonic:
                interval = SHORT_INTERVAL
                if near and monotonic:
                    reason_code = 'NEAR_TOLERANCE'
                    basis = ('最新点距边界' + str(near_distance) + 'V且连续单向漂移' +
                             str(total_shift) + 'V≥' + str(span_v * DRIFT_RATIO) + 'V')
                elif near:
                    reason_code = 'NEAR_TOLERANCE'
                    basis = '最新点距容差边界' + str(near_distance) + 'V，' + threshold_text(low, high)
                else:
                    reason_code = 'DRIFT_MONOTONIC'
                    basis = '连续单向漂移' + str(total_shift) + 'V≥' + \
                            str(span_v * DRIFT_RATIO) + 'V，防止半年周期漏掉持续漂移'
            elif len(good) >= MIN_POINTS_EXTEND and span_days >= MIN_SPAN_DAYS_EXTEND \
                    and excluded_ratio < EXCLUDED_RATIO_CAP and not fluctuation:
                reason_code, interval = 'STABLE_EXTEND', LONG_INTERVAL
                basis = (str(len(good)) + '个有效点跨度' + str(span_days) +
                         '天无显著漂移或波动，失效占比' + str(excluded_pct) + '%')
            else:
                interval = BASE_INTERVAL
                if len(good) < MIN_POINTS_EXTEND or span_days < MIN_SPAN_DAYS_EXTEND:
                    reason_code = 'INSUFFICIENT_HISTORY'
                    basis = ('有效点' + str(len(good)) + '个/跨度' + str(span_days) +
                             '天，未达延长门槛（≥' + str(MIN_POINTS_EXTEND) +
                             '点且≥' + str(MIN_SPAN_DAYS_EXTEND) + '天）')
                elif excluded_ratio >= EXCLUDED_RATIO_CAP:
                    reason_code = 'EVIDENCE_EXCLUDED'
                    basis = ('失效证据' + str(excluded) + '/' + str(total_observations) +
                             '占比' + str(excluded_pct) + '%≥50%，撤销/超量程/溯源中断记录不得作为稳定证据')
                else:
                    reason_code = 'FLUCTUATION_RECOVERED'
                    basis = ('单步波动' + str(max_abs_step) + 'V≥' + str(span_v * DRIFT_RATIO) +
                             'V但已回落，未形成连续单向漂移，维持半年、不予延长')

        last_date = date.fromisoformat(last_day)
        next_date = add_months(last_date, interval)
        plan_id = hashlib.sha256(
            ('plan:' + device + ':' + last_day + ':' + str(interval)).encode('utf-8')
        ).hexdigest()[:12]
        plans.append({
            '计划编号': plan_id, '设备': device,
            '别名': '、'.join(alias_names) or '—',
            '有效点数': len(good) if good else 0, '失效点数': excluded,
            '末次校准日': last_day, '建议间隔_月': interval,
            '下次校准日': next_date.isoformat(),
            '变动原因码': reason_code, '依据': basis,
        })
        for p in points:
            point_rows.append({
                '设备': device, '证书': p['证书'], '校准日': p['校准日'],
                '测量值_V': p['测量值_V'], '下限_V': p['下限_V'], '上限_V': p['上限_V'],
                '采信': '是' if p['采信'] else '否', '原因码': p['原因码'],
                '纳入计划': plan_id if p['采信'] else '—', '行号': p['行号'],
            })

    ctx['interval_plans'] = plans
    metrics = [
        ['设备数', len(plans), '台'],
        ['延长(12月)', sum(p['建议间隔_月'] == LONG_INTERVAL for p in plans), '台'],
        ['维持(6月)', sum(p['建议间隔_月'] == BASE_INTERVAL for p in plans), '台'],
        ['缩短(3月)', sum(p['建议间隔_月'] == SHORT_INTERVAL for p in plans), '台'],
        ['失效校准点', excluded_total, '个'],
    ]
    return {'rows': plans, 'points': point_rows, 'metrics': metrics}
