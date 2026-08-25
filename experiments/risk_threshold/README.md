\# MIRROR Risk Threshold Benchmark



\## Purpose



This experiment evaluates the learned SLA risk model across multiple

classification thresholds.



The production model currently has a threshold of `0.35`.



This benchmark does not change the production policy. It measures the

precision/recall trade-off and evaluates threshold stability under several

false-negative cost assumptions.



\## Dataset Split



\- Training rows: 80,000

\- Held-out rows: 20,000

\- Training/test separation is performed by SKU group.

\- Held-out SKUs: `LAP-041` through `LAP-050`



The held-out evaluation is therefore performed on SKU groups that are not

used for model fitting.



\## Threshold Sweep



The following operating thresholds are evaluated:



`0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60`



For each threshold we record:



\- precision

\- recall

\- F1

\- false negatives

\- false positives



\## Cost Sensitivity



The benchmark uses:



```text

cost = false\_negatives × FN\_cost\_multiplier

&#x20;    + false\_positives

