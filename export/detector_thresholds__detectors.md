# Detectors: detector_thresholds

Commit `b675c9d5c9ddbbdecd2f74f49dcc0462f202d2a9`. 340 runs.

Median across seeds with the interquartile range beside it. `runs` is how many runs each cell is a median over -- a median over five seeds and a median over one look identical otherwise.

| scenario | detector | runs | faults hit | missed | detection recall (IQR) | false alarms/h (IQR) | detection delay s (IQR) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| S4_step_fault | detect_adwin | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.06 [0.06, 0.06] | -- |
| S4_step_fault | detect_adwin_d01 | 10 | 1 | 19 | 0.000 [0.000, 0.000] | 0.06 [0.06, 0.11] | 1698 [1698, 1698] |
| S4_step_fault | detect_adwin_d05 | 10 | 2 | 18 | 0.000 [0.000, 0.000] | 0.06 [0.06, 0.11] | 1478 [1410, 1545] |
| S4_step_fault | detect_adwin_d25 | 10 | 2 | 18 | 0.000 [0.000, 0.000] | 0.06 [0.06, 0.12] | 1478 [1410, 1545] |
| S4_step_fault | detect_adwin_d9 | 10 | 2 | 18 | 0.000 [0.000, 0.000] | 0.12 [0.08, 0.12] | 1478 [1410, 1545] |
| S4_step_fault | detect_cusum | 10 | 3 | 17 | 0.000 [0.000, 0.375] | 0.06 [0.06, 0.12] | 1559 [1475, 1636] |
| S4_step_fault | detect_cusum_h1p5 | 10 | 1 | 19 | 0.000 [0.000, 0.000] | 0.19 [0.19, 0.19] | 1322 [1322, 1322] |
| S4_step_fault | detect_cusum_h3 | 10 | 2 | 18 | 0.000 [0.000, 0.000] | 0.19 [0.19, 0.19] | 911 [705, 1116] |
| S4_step_fault | detect_cusum_h6 | 10 | 3 | 17 | 0.000 [0.000, 0.375] | 0.12 [0.12, 0.12] | 917 [830, 1114] |
| S4_step_fault | detect_ks | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.00 [0.00, 0.06] | -- |
| S4_step_fault | detect_ks_a001 | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.06 [0.02, 0.06] | -- |
| S4_step_fault | detect_ks_a01 | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.06 [0.06, 0.06] | -- |
| S4_step_fault | detect_ks_a1 | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.06 [0.06, 0.06] | -- |
| S4_step_fault | detect_ph | 10 | 1 | 19 | 0.000 [0.000, 0.000] | 0.06 [0.06, 0.06] | 1698 [1698, 1698] |
| S4_step_fault | detect_ph_h1p875 | 10 | 1 | 19 | 0.000 [0.000, 0.000] | 0.19 [0.19, 0.19] | 1322 [1322, 1322] |
| S4_step_fault | detect_ph_h3p75 | 10 | 5 | 15 | 0.250 [0.000, 0.500] | 0.12 [0.08, 0.17] | 691 [593, 1596] |
| S4_step_fault | detect_ph_h7p5 | 10 | 5 | 15 | 0.250 [0.000, 0.500] | 0.06 [0.06, 0.11] | 923 [777, 1181] |
| S6_combined | detect_adwin | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.02 [0.02, 0.04] | -- |
| S6_combined | detect_adwin_d01 | 10 | 1 | 19 | 0.000 [0.000, 0.000] | 0.02 [0.02, 0.04] | 948 [948, 948] |
| S6_combined | detect_adwin_d05 | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.04 [0.03, 0.04] | -- |
| S6_combined | detect_adwin_d25 | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.04 [0.04, 0.04] | -- |
| S6_combined | detect_adwin_d9 | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.04 [0.04, 0.06] | -- |
| S6_combined | detect_cusum | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.04 [0.03, 0.04] | -- |
| S6_combined | detect_cusum_h1p5 | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.08 [0.08, 0.08] | -- |
| S6_combined | detect_cusum_h3 | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.08 [0.08, 0.08] | -- |
| S6_combined | detect_cusum_h6 | 10 | 2 | 18 | 0.000 [0.000, 0.000] | 0.06 [0.06, 0.06] | 1606 [1566, 1646] |
| S6_combined | detect_ks | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.00 [0.00, 0.00] | -- |
| S6_combined | detect_ks_a001 | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.00 [0.00, 0.02] | -- |
| S6_combined | detect_ks_a01 | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.02 [0.01, 0.02] | -- |
| S6_combined | detect_ks_a1 | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.03 [0.02, 0.04] | -- |
| S6_combined | detect_ph | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.03 [0.02, 0.04] | -- |
| S6_combined | detect_ph_h1p875 | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.08 [0.08, 0.08] | -- |
| S6_combined | detect_ph_h3p75 | 10 | 2 | 18 | 0.000 [0.000, 0.000] | 0.06 [0.06, 0.08] | 1519 [1436, 1601] |
| S6_combined | detect_ph_h7p5 | 10 | 0 | 20 | 0.000 [0.000, 0.000] | 0.06 [0.05, 0.06] | -- |

Recall and false alarms are read together or not at all: a detector that alarms on every window has perfect recall, and one that never alarms has no false alarms.

