\# Risk Calibration Experiment



\## Purpose



This experiment evaluates whether post-hoc probability calibration improves MIRROR's learned SLA-risk model enough to justify changing the production decision policy.



Calibration is evaluated separately from classification threshold selection.



\## Experimental Design



The evaluation uses a three-way SKU-held-out split:



\- Training: LAP-001 through LAP-035

\- Calibration: LAP-036 through LAP-040

\- Test: LAP-041 through LAP-050



Rows:



\- Training: 70,000

\- Calibration: 10,000

\- Test: 20,000



The logistic-risk model is fitted only on the training SKUs.



Calibration parameters are fitted only on the calibration SKUs.



Final calibration metrics are computed only on untouched test SKUs.



This prevents the calibration transformation from being fitted on the final evaluation data.



\## Calibration Method



Post-hoc logistic/Platt calibration is applied to the raw model probabilities.



The experiment compares:



1\. Raw model probabilities

2\. Calibrated probabilities



The goal is to determine whether calibrated probabilities better represent observed event frequencies without changing the model's ranking ability.



\## Results



Raw test calibration:



\- Brier score: 0.05316

\- Expected calibration error: 0.13042

\- ROC-AUC: approximately 0.99608



Calibrated test results:



\- Brier score: 0.02536

\- Expected calibration error: 0.02320

\- ROC-AUC: approximately 0.99608



Calibration therefore substantially improves probability calibration on the locked synthetic test set while preserving discrimination.



The ROC-AUC difference is effectively zero because monotonic calibration preserves the ordering of predictions.



\## Decision-Threshold Findings



Calibration was also evaluated against the decision policy using multiple thresholds and hypothetical false-negative cost multipliers.



Observed calibrated-policy optima:



| FN Cost Multiplier | Best Calibrated Threshold | FP | FN |

|---:|---:|---:|---:|

| 10x | 0.015 | 692 | 89 |

| 25x | 0.001 | 1378 | 25 |

| 50x | 0.001 | 1378 | 25 |

| 100x | 0.001 | 1378 | 25 |



The low thresholds are a warning rather than evidence that MIRROR should immediately adopt them.



The optimum reaches the lower edge of the tested probability range for several cost scenarios. This indicates that the calibrated probability scale does not currently produce a stable, universally defensible production threshold.



\## Production Decision



Post-hoc calibration is \*\*not enabled in the production decision path\*\* at this stage.



The current production policy remains based on the existing raw model score and its independently evaluated threshold policy.



This is intentional.



The experiment demonstrates that calibration improves statistical probability quality on the locked synthetic dataset, but that improvement alone does not establish that calibrated probabilities produce a better operational decision policy.



\## Cost Sensitivity Caveat



The false-negative cost multipliers used in this experiment are sensitivity-analysis assumptions.



They are not measured production business costs.



Therefore the resulting thresholds must not be interpreted as financially optimal production thresholds.



\## Limitations



This experiment uses locked synthetic data.



It does not establish calibration quality on real merchant traffic.



The calibration parameters and threshold recommendations therefore require validation against real production outcomes before being considered for deployment.



\## Reproducibility



Run:



```powershell

python experiments\\risk\_calibration\\benchmark.py

