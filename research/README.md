# Phytosense++ Research

## Objective
Evaluate sensor signal-quality gating and bounded-memory anomaly detection for bioelectric sensor data.

## Repository Structure
- `analysis/replay_eval.py`: Replay evaluation of gated and ungated detection.
- `analysis/build_baseline_model.py`: Baseline and gating-ablation experiment.
- `research/results/replay_eval_summary.txt`: Saved replay evaluation summary.
- `research/data_public/`: Local datasets, excluded from Git.

## Requirements
Python 3, NumPy, pandas, and Matplotlib.

## Run Replay Evaluation
From the repository root:
`python analysis/replay_eval.py research/data_public/phytosense_trial_log_full.csv research/results`

## Current Preliminary Results
- Fault-period samples rejected: 80.3 percent.
- Clean-period samples rejected: 0.00 percent.
- Simulated fault samples caught: 70.6 percent.

These results are preliminary and require further validation. Simulated and recorded fault results should be reported separately.

## Data
Raw datasets are kept locally and excluded from version control. Obtain permission and follow the appropriate data-sharing rules before distributing any dataset.
