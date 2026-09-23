# Detectors: detectors

Commit `8cda5fd98865bccfe8601ace6f9a27d5a835513e`. 100 runs.

Median across seeds with the interquartile range beside it. `runs` is how many runs each cell is a median over -- a median over five seeds and a median over one look identical otherwise.

| scenario | detector | runs | faults hit | missed | detection recall (IQR) | false alarms/h (IQR) | detection delay s (IQR) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| S4_step_fault | detect_adwin | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.06 [0.06, 0.06] | -- |
| S4_step_fault | detect_all4 | 10 | 3 | 17 | 0.000 [0.000, 0.375] | 0.06 [0.06, 0.12] | 1559 [1475, 1636] |
| S4_step_fault | detect_cusum | 10 | 3 | 17 | 0.000 [0.000, 0.375] | 0.06 [0.06, 0.12] | 1559 [1475, 1636] |
| S4_step_fault | detect_ks | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.00 [0.00, 0.06] | -- |
| S4_step_fault | detect_ph | 10 | 1 | 19 | 0.000 [0.000, 0.000] | 0.06 [0.06, 0.06] | 1698 [1698, 1698] |
| S6_combined | detect_adwin | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.02 [0.02, 0.04] | -- |
| S6_combined | detect_all4 | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.04 [0.03, 0.04] | -- |
| S6_combined | detect_cusum | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.04 [0.03, 0.04] | -- |
| S6_combined | detect_ks | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.00 [0.00, 0.00] | -- |
| S6_combined | detect_ph | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.03 [0.02, 0.04] | -- |

Recall and false alarms are read together or not at all: a detector that alarms on every window has perfect recall, and one that never alarms has no false alarms.

