"""Offline verification harness for the Sonar Battleship DSP layer.

Run with:  python game/dsp_harness.py

Pure NumPy — it does not touch Django or the database, so it runs
without a server. Section 7 prints the accuracy-vs-noise table the
Week 6 write-up asks for.

Not part of the Django app — this just exercises signal_engine +
signal_processor over many random trials so we can see the detector's
behaviour without playing hundreds of games by hand.
"""
import os
import sys
import math
import statistics

# Run from anywhere: python game/dsp_harness.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from game import signal_engine as se
from game import signal_processor as sp

GRID = 10
rng = np.random.default_rng(7)


def ship(size, r, c, orient='H', sunk=False):
    cells = [[r, c + i] if orient == 'H' else [r + i, c] for i in range(size)]
    return {'size': size, 'cells': cells, 'hit_cells': [], 'is_sunk': sunk}


def bearing(origin, target):
    import math
    dr = target[0] - origin[0]
    dc = target[1] - origin[1]
    b = math.degrees(math.atan2(dc, -dr))
    return b + 360 if b < 0 else b


def hr(title):
    print('\n' + '=' * 66)
    print(title)
    print('=' * 66)


# ------------------------------------------------------------------
hr('1. IDLE OCEAN NOISE — should almost never report a detection')
false_alarms = 0
types = {}
TRIALS = 400
for _ in range(TRIALS):
    sig = se.generate_idle_signals(1)[0]['signal']
    out = sp.processSignal(sig)
    if out['detected']:
        false_alarms += 1
        types[out['signal_type']] = types.get(out['signal_type'], 0) + 1
print(f'false alarms: {false_alarms}/{TRIALS}  ({100*false_alarms/TRIALS:.1f}%)  {types}')

confs = []
for _ in range(200):
    sig = se.generate_idle_signals(1)[0]['signal']
    confs.append(sp.processSignal(sig)['confidence'])
print(f'idle confidence: mean {statistics.mean(confs):.3f}  max {max(confs):.3f}')


# ------------------------------------------------------------------
hr('2. SONAR ECHO — classification, distance accuracy, size estimate')
me = [ship(3, 8, 1, 'H')]                      # my boat, bottom-left
rows = []
for size in (3, 4, 5):
    err, size_err, det, cls_ok, confs = [], [], 0, 0, []
    for trial in range(120):
        er = int(rng.integers(0, GRID))
        target = ship(size, er, 3, 'H')
        origin = (8, 1)
        # aim straight at the target's nearest cell
        tgt_unified = (er, 3 + GRID)
        ang = bearing(origin, tgt_unified)
        sigs = se.generate_sonar_echo(origin, ang, me, [target], GRID, 'left')
        truth = sigs[0]['target_distance']
        out = sp.processSignal(sigs[0]['signal'])
        confs.append(out['confidence'])
        if out['detected']:
            det += 1
            if out['signal_type'] == 'sonar':
                cls_ok += 1
                err.append(abs(out['estimated_distance'] - truth))
                if out['estimated_size'] is not None:
                    size_err.append(out['estimated_size'] - size)
    rows.append((size, det, cls_ok, err, size_err, confs))

print(f"{'size':>4} {'detect':>8} {'as sonar':>9} {'dist err':>10} {'size bias':>10} {'|size err|<=1':>14} {'conf':>6}")
for size, det, cls_ok, err, size_err, confs in rows:
    de = f'{statistics.mean(err):.2f}' if err else '-'
    sb = f'{statistics.mean(size_err):+.2f}' if size_err else '-'
    within = f'{100*sum(1 for e in size_err if abs(e)<=1)/len(size_err):.0f}%' if size_err else '-'
    print(f'{size:>4} {det:>7}/120 {cls_ok:>8}/120 {de:>10} {sb:>10} {within:>14} {statistics.mean(confs):>6.2f}')


# ------------------------------------------------------------------
hr('3. FRIENDLY HULL IN THE BEAM — sonar must be blocked')
# my firing boat at (5,0) pointing east; another of my boats sits at (5,3)
shooter = ship(3, 5, 0, 'H')          # occupies (5,0),(5,1),(5,2)
friend = ship(4, 5, 4, 'H')           # occupies (5,4)..(5,7)  -> in the way
enemy = [ship(5, 5, 2, 'H')]          # far side, same row
my_fleet = [shooter, friend]
origin = (5, 0)
ang = 90.0  # due east

sigs = se.generate_sonar_echo(origin, ang, my_fleet, enemy, GRID, 'left')
print(f"blocked={sigs[0]['blocked']}  blocker_size={sigs[0]['blocked_by_size']}  "
      f"blocker_dist={sigs[0]['blocker_distance']}  target_distance={sigs[0]['target_distance']}")
assert sigs[0]['blocked'] is True, 'friendly hull did NOT block the beam'
assert sigs[0]['target_distance'] is None, 'enemy leaked through a blocked beam'

# same geometry, friend removed -> must get through
sigs2 = se.generate_sonar_echo(origin, ang, [shooter], enemy, GRID, 'left')
print(f"without the friendly boat: blocked={sigs2[0]['blocked']}  "
      f"target_distance={sigs2[0]['target_distance']}  target_size={sigs2[0]['target_size']}")
assert sigs2[0]['blocked'] is False and sigs2[0]['target_distance'] is not None

# the shooter's own hull must never block itself
shooter_long = ship(5, 5, 0, 'H')
sigs3 = se.generate_sonar_echo((5, 0), 90.0, [shooter_long], enemy, GRID, 'left')
print(f"origin boat blocking itself? blocked={sigs3[0]['blocked']} (must be False)")
assert sigs3[0]['blocked'] is False

# a sunk friendly wreck should not block
wreck = ship(4, 5, 4, 'H', sunk=True)
sigs4 = se.generate_sonar_echo((5, 0), 90.0, [shooter, wreck], enemy, GRID, 'left')
print(f"sunk friendly wreck blocks? blocked={sigs4[0]['blocked']} (must be False)")
assert sigs4[0]['blocked'] is False

# off-bearing friend should not block
sigs5 = se.generate_sonar_echo((5, 0), 45.0, [shooter, friend], enemy, GRID, 'left')
print(f"friend off-bearing (45 deg) blocks? blocked={sigs5[0]['blocked']} (must be False)")
assert sigs5[0]['blocked'] is False
print('blocking checks PASSED')


# ------------------------------------------------------------------
hr('4. BOMB HIT vs BOMB MISS — must be detected separately')
my_ships = [ship(4, 4, 2, 'H')]
confusion = {}
for label, is_hit, hit_size in (('miss', False, None), ('hit-3', True, 3),
                                ('hit-4', True, 4), ('hit-5', True, 5)):
    counts, sizes = {}, []
    for _ in range(120):
        sigs = se.generate_bomb_shockwave_signals(
            (5, 5), my_ships, GRID, 'left', target_side='enemy',
            hit=is_hit, hit_ship_size=hit_size)
        out = sp.processSignal(sigs[0]['signal'])
        counts[out['signal_type']] = counts.get(out['signal_type'], 0) + 1
        if is_hit and out['estimated_size'] is not None:
            sizes.append(out['estimated_size'])
    confusion[label] = counts
    extra = f"  est size mean {statistics.mean(sizes):.1f}" if sizes else ''
    print(f'{label:>6} -> {counts}{extra}')

assert confusion['miss'].get('bomb_hit', 0) <= 1, 'a miss was reported as a hit'
for k in ('hit-3', 'hit-4', 'hit-5'):
    total = sum(confusion[k].values())
    assert confusion[k].get('bomb_hit', 0) / total > 0.93, f'{k} not reliably a hit'
print('hit/miss separation PASSED')


# ------------------------------------------------------------------
hr('5. DEFENDER COORDINATE FRAME — bomb on my own grid')
# Enemy bombs cell (4,3) on MY grid; my boat sits right there.
mine = [ship(3, 4, 2, 'H')]
own = se.generate_bomb_shockwave_signals((4, 3), mine, GRID, 'left',
                                         target_side='mine', hit=True, hit_ship_size=3)
print(f"defender range to a blast on its own hull: {own[0]['target_distance']} cells (expect 0.0)")
assert own[0]['target_distance'] == 0.0

wrong = se.generate_bomb_shockwave_signals((4, 3), mine, GRID, 'left',
                                           target_side='enemy', hit=True, hit_ship_size=3)
print(f"same blast with the old (enemy) frame: {wrong[0]['target_distance']} cells — the bug")


# ------------------------------------------------------------------
hr('6. DISTANCE HYPOTHESES — echo vs direct arrival')
d_true = 6.0
delay_echo = se.distance_to_delay(d_true, round_trip=True)
delay_direct = se.distance_to_delay(d_true, round_trip=False)
print(f'round-trip delay {delay_echo:.3f}s -> {sp.delay_to_distance(delay_echo, True):.2f} cells')
print(f'one-way   delay {delay_direct:.3f}s -> {sp.delay_to_distance(delay_direct, False):.2f} cells')
assert abs(sp.delay_to_distance(delay_echo, True) - d_true) < 1e-9
assert abs(sp.delay_to_distance(delay_direct, False) - d_true) < 1e-9
print('delay <-> distance round trip PASSED')


# ------------------------------------------------------------------
hr('7. CONFIDENCE vs NOISE — the meter must track detectability')
me1 = [ship(3, 8, 1, 'H')]
target = [ship(4, 5, 3, 'H')]
origin = (8, 1)
ang = bearing(origin, (5, 3 + GRID))
base_noise = se.NOISE_LEVEL
print(f"{'noise sigma':>12} {'detect rate':>12} {'mean conf':>10} {'mean dist err':>14} {'conf>1 or <0':>13}")
for noise in (0.05, 0.10, 0.15, 0.25, 0.40, 0.70):
    se.NOISE_LEVEL = noise
    det, confs, errs, out_of_range = 0, [], [], 0
    for _ in range(150):
        sigs = se.generate_sonar_echo(origin, ang, me1, target, GRID, 'left')
        truth = sigs[0]['target_distance']
        out = sp.processSignal(sigs[0]['signal'])
        confs.append(out['confidence'])
        if not (0.0 <= out['confidence'] <= 1.0):
            out_of_range += 1
        if out['detected'] and out['signal_type'] == 'sonar':
            det += 1
            errs.append(abs(out['estimated_distance'] - truth))
    e = f'{statistics.mean(errs):.2f}' if errs else '-'
    print(f'{noise:>12.2f} {100*det/150:>11.0f}% {statistics.mean(confs):>10.2f} {e:>14} {out_of_range:>13}')
se.NOISE_LEVEL = base_noise



# ------------------------------------------------------------------
hr('8. PASSIVE COUNTER-DETECTION — active sonar gives you away')

# Import the database-free half of the counter-detection logic. It lives
# in game_logic, which imports Django models at module scope, so pull the
# pure function out by source rather than importing the module.
import types as _types
import re as _re

_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         'game_logic.py'), encoding='utf-8').read()
_start = _src.index('def _to_unified(')
_end = _src.index('# ============================================================\n# Fire')
_mod = _types.ModuleType('counter_pure')
_mod.__dict__.update({
    'math': __import__('math'),
    'generate_incoming_sonar_signals': se.generate_incoming_sonar_signals,
    'process_signal': sp.processSignal,
})
exec(compile(_src[_start:_end], 'game_logic.py(pure)', 'exec'), _mod.__dict__)
counter_detect_from_ships = _mod.counter_detect_from_ships

# We sit on the LEFT. The enemy transmits from cell (5,3) of THEIR grid,
# which is column 13 in the shared coordinate space — due east of us.
FLEET = [ship(5, 1, 1), ship(4, 5, 2), ship(3, 8, 1)]
SOLO = [ship(4, 5, 2)]


def listen(fleet, angle, trials=100):
    return [counter_detect_from_ships([5, 3], angle, fleet, GRID, 'left')
            for _ in range(trials)]


print(f"{'their beam':>26} {'heard':>8} {'bearing fix':>13}")
for angle, desc in ((270, 'straight at us'), (300, '30 deg off us'),
                    (330, '60 deg off us'), (90, 'aimed away from us')):
    rows = listen(FLEET, angle)
    heard = sum(1 for r in rows if r['detected'])
    fixed = sum(1 for r in rows if r.get('fix_quality') == 'fix')
    print(f'{angle:>4}  {desc:>19} {100*heard/len(rows):7.0f}% {100*fixed/len(rows):12.0f}%')

# A ping aimed at us must be much more audible than one aimed away.
toward = sum(1 for r in listen(FLEET, 270) if r['detected'])
away = sum(1 for r in listen(FLEET, 90) if r['detected'])
assert toward > away * 3, 'beam direction barely affects counter-detection'

# One surviving boat is one hydrophone: a range circle, never a bearing.
solo = [r for r in listen(SOLO, 270) if r['detected']]
assert solo, 'a lone boat heard nothing at all'
assert all(r['fix_quality'] == 'range_only' for r in solo), \
    'a single hydrophone produced a bearing it cannot possibly measure'
print(f'\nsingle hydrophone: {len(solo)} detections, all range-only (correct — '
      f'one arrival time carries no direction)')

# Accuracy of the fixes we do get.
fixes = [r for r in listen(FLEET, 270, 200) if r.get('fix_quality') == 'fix']
if fixes:
    b_err, r_err = [], []
    for r in fixes:
        lr, lc = r['listener_cell']
        true_b = math.degrees(math.atan2(13 - lc, -(5 - lr))) % 360
        true_r = math.hypot(5 - lr, 13 - lc)
        e = abs(r['bearing'] - true_b)
        b_err.append(min(e, 360 - e))
        r_err.append(abs(r['range'] - true_r))
    print(f'{len(fixes)} bearing fixes: bearing error median '
          f'{statistics.median(b_err):.1f} deg, range error median '
          f'{statistics.median(r_err):.2f} cells')

print('\ncounter-detection vs ocean noise (their beam aimed at us):')
_base = se.NOISE_LEVEL
for n in (0.05, 0.15, 0.30, 0.60):
    se.NOISE_LEVEL = n
    rows = listen(FLEET, 270, 80)
    heard = sum(1 for r in rows if r['detected'])
    fixed = sum(1 for r in rows if r.get('fix_quality') == 'fix')
    print(f'  sigma {n:.2f} -> heard {100*heard/len(rows):3.0f}%   '
          f'bearing fix {100*fixed/len(rows):3.0f}%')
se.NOISE_LEVEL = _base
print('counter-detection checks PASSED')

print('\nAll assertions passed.')
