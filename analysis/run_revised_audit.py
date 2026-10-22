"""Run the revised benchmark and full tests while preserving completed phase outputs."""
import subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
REQUIRED=[ROOT/'reports'/'audit_report.md',ROOT/'reports'/'real_fault_analysis.md',ROOT/'reports'/'gate_ablation.md',ROOT/'reports'/'baseline_absorption.md',ROOT/'out'/'revised'/'real_fault_metrics.csv',ROOT/'out'/'revised'/'gate_ablation.csv',ROOT/'out'/'revised'/'window_sweep.csv']
missing=[str(p.relative_to(ROOT)) for p in REQUIRED if not p.exists()]
if missing: raise SystemExit('Completed prior-phase outputs are missing; refusing to regenerate them: '+', '.join(missing))
STEPS=[[sys.executable,'analysis/benchmark_revised.py'],[sys.executable,'-m','pytest','-q']]
print('Reusing completed audit, fault replay, gate ablation, and absorption outputs without overwriting them.',flush=True)
for step in STEPS:
    print('+',' '.join(step),flush=True)
    subprocess.run(step,cwd=ROOT,check=True)
