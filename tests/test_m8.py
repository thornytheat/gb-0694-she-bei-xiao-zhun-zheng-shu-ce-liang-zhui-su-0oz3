import csv
import io
from datetime import date
from pathlib import Path
import pytest
from app.config import HISTORY_SAMPLE
from app.pipeline import calculate
from app.modules.m8_interval.rules import add_months

HISTORY = HISTORY_SAMPLE.read_text(encoding='utf-8-sig')
FIELDS = list(csv.DictReader(io.StringIO(HISTORY)).fieldnames)


@pytest.fixture
def ctx():
    return calculate(HISTORY, stop=8)


def run_with(rows):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    return calculate(out.getvalue(), stop=8)


def history_rows():
    return list(csv.DictReader(io.StringIO(HISTORY)))


def plan(ctx, device):
    return next(p for p in ctx['stages']['8']['rows'] if p['设备'] == device)


def test_stable_device_extends_to_year(ctx):
    p = plan(ctx, 'D1001')
    assert p['建议间隔_月'] == 12 and p['变动原因码'] == 'STABLE_EXTEND'
    assert p['下次校准日'] == '2027-11-15'


def test_monotonic_drift_shortens(ctx):
    p = plan(ctx, 'D1002')
    assert p['建议间隔_月'] == 3 and p['变动原因码'] == 'DRIFT_MONOTONIC'
    assert p['下次校准日'] == '2027-02-15'


def test_one_off_fluctuation_keeps_half_year(ctx):
    p = plan(ctx, 'D1003')
    assert p['建议间隔_月'] == 6 and p['变动原因码'] == 'FLUCTUATION_RECOVERED'


def test_near_tolerance_shortens(ctx):
    p = plan(ctx, 'D1004')
    assert p['建议间隔_月'] == 3 and p['变动原因码'] == 'NEAR_TOLERANCE'
    assert '0.60V' in p['依据']


def test_renamed_device_merges_history(ctx):
    # D1005 与 D1005-OLD 是同一台仪器，5 个校准点必须归并后才能满足延长门槛。
    devices = {p['设备'] for p in ctx['stages']['8']['rows']}
    assert 'D1005-OLD' not in devices
    p = plan(ctx, 'D1005')
    assert p['有效点数'] == 5 and p['建议间隔_月'] == 12
    assert '旧编码仪表' in p['别名']


def test_revoked_and_out_of_range_never_stable_evidence(ctx):
    points = [p for p in ctx['stages']['8']['points'] if p['设备'] == 'D1006']
    assert {p['采信'] for p in points} == {'是', '否'}
    excluded = {p['原因码'] for p in points if p['采信'] == '否'}
    assert 'REVOKED' in excluded and 'OUT_OF_RANGE' in excluded
    assert all(p['纳入计划'] == '—' for p in points if p['采信'] == '否')


def test_broken_traceability_excluded(ctx):
    p = plan(ctx, 'D1008')
    assert p['有效点数'] == 0 and p['建议间隔_月'] == 3
    assert p['变动原因码'] == 'NO_VALID_EVIDENCE'
    assert 'MISSING_REFERENCE' in p['依据'] and 'REVOKED' in p['依据']


def test_short_history_keeps_base_interval(ctx):
    p = plan(ctx, 'D1007')
    assert p['建议间隔_月'] == 6 and p['变动原因码'] == 'INSUFFICIENT_HISTORY'
    assert p['有效点数'] == 2 and p['失效点数'] == 1


def test_wide_range_reference_not_flagged_near_tolerance(ctx):
    # 标准源全量程 1000V，比例阈值不适用于宽量程仪器。
    p = plan(ctx, 'REF-001')
    assert p['变动原因码'] == 'INSUFFICIENT_HISTORY'


def test_evidence_points_linked_to_plan(ctx):
    for p in ctx['stages']['8']['points']:
        if p['采信'] == '是':
            target = plan(ctx, p['设备'])
            assert p['纳入计划'] == target['计划编号']


def test_thresholds_frozen_in_manifest(ctx):
    params = ctx['manifest']['parameters']
    assert params['near_limit_ratio'] == '0.1'
    assert params['interval_ladder_months'] == [3, 6, 12]


def test_point_conservation_per_device(ctx):
    plans = {p['设备']: p for p in ctx['stages']['8']['rows']}
    for device, p in plans.items():
        observed = sum(1 for q in ctx['stages']['8']['points'] if q['设备'] == device)
        assert observed == p['有效点数'] + p['失效点数']
    assert len(plans) == len({q['设备'] for q in ctx['stages']['8']['points']})


def test_add_months_clamps_to_month_end():
    assert add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)
    assert add_months(date(2026, 11, 15), 6) == date(2027, 5, 15)


def test_upstream_change_recomputes_plan(ctx):
    # 上游把最近一次校准更新为持续上漂序列，计划应随内容重算并生成新批次。
    rows = history_rows()
    revised = []
    for r in rows:
        if r['device'] in ('D1001',) or r['cert'] == 'ROOT':
            if r['cert'] == 'ROOT':
                revised.append(r)
            else:
                value = {'H1001A': '5.00', 'H1001B': '5.20', 'H1001C': '5.45',
                         'H1001D': '5.75', 'H1001E': '6.10'}[r['cert']]
                revised.append({**r, 'value': value})
    new = run_with(revised)
    assert new['manifest']['run_id'] != ctx['manifest']['run_id']
    assert plan(new, 'D1001')['建议间隔_月'] == 3
    assert plan(new, 'D1001')['变动原因码'] == 'DRIFT_MONOTONIC'


def test_rerun_same_batch_creates_no_duplicate_plans(client):
    first = client.post('/api/run', json={'csv': HISTORY}).get_json()
    second = client.post('/api/run', json={'csv': HISTORY}).get_json()
    assert first['manifest']['run_id'] == second['manifest']['run_id']
    assert second['reused'] is True
    plans = client.get('/api/runs/' + first['manifest']['run_id'] + '/plans').get_json()
    assert len(plans) == len(first['stages']['8']['rows'])
    assert len({p['计划编号'] for p in plans}) == len(plans)


def test_m8_endpoint_and_page(client):
    assert client.post('/api/m8', json={'csv': HISTORY}).get_json()['stage'] == 8
    run = client.post('/api/run', json={'csv': HISTORY}).get_json()
    page = client.get('/work/8?run_id=' + run['manifest']['run_id']).data.decode()
    assert '采用的校准点与变动原因' in page and 'STABLE_EXTEND' in page


def test_plans_of_unknown_batch_404(client):
    assert client.get('/api/runs/absent/plans').status_code == 404


def test_evidence_csv_contains_calibration_points(client):
    run = client.post('/api/run', json={'csv': HISTORY}).get_json()
    text = client.get('/api/evidence.csv?run_id=' + run['manifest']['run_id']).data.decode('utf-8-sig')
    assert '8-校准点' in text and 'REVOKED' in text


def test_sparse_history_does_not_falsely_flag_drift():
    # 仅有两个点时即使差值较大，也不得判为单向漂移或接近容差。
    rows = history_rows()
    keep = [r for r in rows if r['device'] in ('REF-001',) or r['cert'] in ('H1001A', 'H1001B')]
    keep = [{**r, 'device': 'D2001'} if r['cert'].startswith('H1001') else r for r in keep]
    keep[-1]['value'] = '5.90'
    ctx = run_with(keep)
    p = plan(ctx, 'D2001')
    assert p['建议间隔_月'] == 6 and p['变动原因码'] == 'INSUFFICIENT_HISTORY'
