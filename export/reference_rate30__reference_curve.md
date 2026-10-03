# The reference-rate curve: reference_rate30

Commit `1d4529356ecdbca4f32d726eac961fc3119b5c1d`. 1260 runs. Rates run: 1 in 1, 1 in 2, 1 in 3, 1 in 5, 1 in 10, 1 in 20, 1 in 50.

## A1 -- detection recall against reference rate

**Governed arm only.** With the controller disabled the detectors are never constructed, so every ungoverned run in this sweep reports `alarms 0, detected 0, recall 0.000`. Those are structural zeros and pooling the two arms would halve every recall below while presenting 'the detector was not running' as 'the detector missed'.

Recall is `detected / (detected + missed)` over the calibration faults injected into the scenario, crediting only alarms that fired *after* a fault and within the scoring horizon. The mean is given as well as the median because recall over two or three injected faults takes a few discrete values, and a cell that plainly detected something can still have a median of 0.000. Detection delay is a median over the runs that detected anything at all; `n delay` says how many those were, and a run that detected nothing contributes no delay rather than a zero.

| scenario | estimator | 1 in | runs | recall mean | recall median (IQR) | hit | missed | n delay | delay s (IQR) | false alarms/h |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| S4_step_fault | kalman | 1 | 15 | 0.533 | 0.500 [0.500, 0.750] | 16 | 14 | 12 | 427 [228, 781] | 1.00 |
| S4_step_fault | kalman | 2 | 15 | 0.367 | 0.500 [0.000, 0.500] | 11 | 19 | 10 | 438 [233, 627] | 0.50 |
| S4_step_fault | kalman | 3 | 15 | 0.467 | 0.500 [0.000, 0.750] | 14 | 16 | 10 | 801 [570, 1272] | 0.31 |
| S4_step_fault | kalman | 5 | 15 | 0.300 | 0.500 [0.000, 0.500] | 9 | 21 | 8 | 815 [535, 1161] | 0.19 |
| S4_step_fault | kalman | 10 | 15 | 0.300 | 0.500 [0.000, 0.500] | 9 | 21 | 9 | 1030 [787, 1424] | 0.06 |
| S4_step_fault | kalman | 20 | 15 | 0.033 | 0.000 [0.000, 0.000] | 1 | 29 | 1 | 1607 [1607, 1607] | 0.06 |
| S4_step_fault | kalman | 50 | 15 | 0.000 | 0.000 [0.000, 0.000] | 0 | 30 | 0 | -- | 0.00 |
| S4_step_fault | rls | 1 | 15 | 0.600 | 0.500 [0.500, 1.000] | 18 | 12 | 12 | 292 [171, 759] | 1.00 |
| S4_step_fault | rls | 2 | 15 | 0.433 | 0.500 [0.250, 0.500] | 13 | 17 | 11 | 400 [270, 639] | 0.44 |
| S4_step_fault | rls | 3 | 15 | 0.367 | 0.500 [0.000, 0.500] | 11 | 19 | 8 | 1120 [443, 1266] | 0.38 |
| S4_step_fault | rls | 5 | 15 | 0.267 | 0.500 [0.000, 0.500] | 8 | 22 | 8 | 640 [387, 1094] | 0.19 |
| S4_step_fault | rls | 10 | 15 | 0.300 | 0.500 [0.000, 0.500] | 9 | 21 | 9 | 1030 [777, 1181] | 0.06 |
| S4_step_fault | rls | 20 | 15 | 0.033 | 0.000 [0.000, 0.000] | 1 | 29 | 1 | 1786 [1786, 1786] | 0.06 |
| S4_step_fault | rls | 50 | 15 | 0.000 | 0.000 [0.000, 0.000] | 0 | 30 | 0 | -- | 0.00 |
| S4_step_fault | static_affine | 1 | 15 | 0.700 | 0.500 [0.500, 1.000] | 21 | 9 | 14 | 692 [233, 1079] | 0.94 |
| S4_step_fault | static_affine | 2 | 15 | 0.467 | 0.500 [0.000, 0.750] | 14 | 16 | 10 | 463 [372, 536] | 0.44 |
| S4_step_fault | static_affine | 3 | 15 | 0.267 | 0.000 [0.000, 0.500] | 8 | 22 | 7 | 500 [279, 992] | 0.31 |
| S4_step_fault | static_affine | 5 | 15 | 0.167 | 0.000 [0.000, 0.250] | 5 | 25 | 4 | 591 [526, 712] | 0.19 |
| S4_step_fault | static_affine | 10 | 15 | 0.367 | 0.500 [0.250, 0.500] | 11 | 19 | 11 | 787 [663, 1123] | 0.06 |
| S4_step_fault | static_affine | 20 | 15 | 0.000 | 0.000 [0.000, 0.000] | 0 | 30 | 0 | -- | 0.06 |
| S4_step_fault | static_affine | 50 | 15 | 0.000 | 0.000 [0.000, 0.000] | 0 | 30 | 0 | -- | 0.00 |
| S4_step_fault | all | 1 | 45 | 0.611 | 0.500 [0.500, 1.000] | 55 | 35 | 38 | 405 [209, 883] | 1.00 |
| S4_step_fault | all | 2 | 45 | 0.422 | 0.500 [0.000, 0.500] | 38 | 52 | 31 | 428 [287, 549] | 0.50 |
| S4_step_fault | all | 3 | 45 | 0.367 | 0.500 [0.000, 0.500] | 33 | 57 | 25 | 826 [313, 1257] | 0.31 |
| S4_step_fault | all | 5 | 45 | 0.244 | 0.000 [0.000, 0.500] | 22 | 68 | 20 | 604 [432, 1041] | 0.19 |
| S4_step_fault | all | 10 | 45 | 0.322 | 0.500 [0.000, 0.500] | 29 | 61 | 29 | 1030 [742, 1391] | 0.06 |
| S4_step_fault | all | 20 | 45 | 0.022 | 0.000 [0.000, 0.000] | 2 | 88 | 2 | 1697 [1652, 1741] | 0.06 |
| S4_step_fault | all | 50 | 45 | 0.000 | 0.000 [0.000, 0.000] | 0 | 90 | 0 | -- | 0.00 |
| S7_sparse_reference | kalman | 1 | 15 | 0.933 | 1.000 [1.000, 1.000] | 14 | 1 | 14 | 700 [299, 947] | 2.83 |
| S7_sparse_reference | kalman | 2 | 15 | 0.667 | 1.000 [0.000, 1.000] | 10 | 5 | 10 | 937 [686, 1382] | 1.33 |
| S7_sparse_reference | kalman | 3 | 15 | 0.200 | 0.000 [0.000, 0.000] | 3 | 12 | 3 | 1142 [758, 1299] | 0.92 |
| S7_sparse_reference | kalman | 5 | 15 | 0.200 | 0.000 [0.000, 0.000] | 3 | 12 | 3 | 382 [200, 687] | 0.50 |
| S7_sparse_reference | kalman | 10 | 15 | 0.200 | 0.000 [0.000, 0.000] | 3 | 12 | 3 | 1304 [1217, 1364] | 0.25 |
| S7_sparse_reference | kalman | 20 | 15 | 0.200 | 0.000 [0.000, 0.000] | 3 | 12 | 3 | 1129 [1043, 1413] | 0.17 |
| S7_sparse_reference | kalman | 50 | 15 | 0.067 | 0.000 [0.000, 0.000] | 1 | 14 | 1 | 1239 [1239, 1239] | 0.08 |
| S7_sparse_reference | rls | 1 | 15 | 0.933 | 1.000 [1.000, 1.000] | 14 | 1 | 14 | 700 [378, 869] | 2.75 |
| S7_sparse_reference | rls | 2 | 15 | 0.800 | 1.000 [1.000, 1.000] | 12 | 3 | 12 | 758 [418, 1129] | 1.33 |
| S7_sparse_reference | rls | 3 | 15 | 0.200 | 0.000 [0.000, 0.000] | 3 | 12 | 3 | 374 [194, 946] | 0.92 |
| S7_sparse_reference | rls | 5 | 15 | 0.200 | 0.000 [0.000, 0.000] | 3 | 12 | 3 | 993 [687, 1043] | 0.50 |
| S7_sparse_reference | rls | 10 | 15 | 0.267 | 0.000 [0.000, 0.500] | 4 | 11 | 4 | 1217 [1102, 1334] | 0.25 |
| S7_sparse_reference | rls | 20 | 15 | 0.200 | 0.000 [0.000, 0.000] | 3 | 12 | 3 | 1696 [1413, 1697] | 0.08 |
| S7_sparse_reference | rls | 50 | 15 | 0.067 | 0.000 [0.000, 0.000] | 1 | 14 | 1 | 1239 [1239, 1239] | 0.08 |
| S7_sparse_reference | static_affine | 1 | 15 | 0.933 | 1.000 [1.000, 1.000] | 14 | 1 | 14 | 700 [527, 913] | 2.83 |
| S7_sparse_reference | static_affine | 2 | 15 | 0.667 | 1.000 [0.000, 1.000] | 10 | 5 | 10 | 962 [797, 1401] | 1.33 |
| S7_sparse_reference | static_affine | 3 | 15 | 0.533 | 1.000 [0.000, 1.000] | 8 | 7 | 8 | 550 [303, 801] | 0.92 |
| S7_sparse_reference | static_affine | 5 | 15 | 0.400 | 0.000 [0.000, 1.000] | 6 | 9 | 6 | 620 [155, 1219] | 0.58 |
| S7_sparse_reference | static_affine | 10 | 15 | 0.200 | 0.000 [0.000, 0.000] | 3 | 12 | 3 | 1304 [1217, 1395] | 0.25 |
| S7_sparse_reference | static_affine | 20 | 15 | 0.200 | 0.000 [0.000, 0.000] | 3 | 12 | 3 | 1696 [970, 1697] | 0.17 |
| S7_sparse_reference | static_affine | 50 | 15 | 0.067 | 0.000 [0.000, 0.000] | 1 | 14 | 1 | 1239 [1239, 1239] | 0.08 |
| S7_sparse_reference | all | 1 | 45 | 0.933 | 1.000 [1.000, 1.000] | 42 | 3 | 42 | 700 [323, 897] | 2.83 |
| S7_sparse_reference | all | 2 | 45 | 0.711 | 1.000 [0.000, 1.000] | 32 | 13 | 32 | 818 [644, 1389] | 1.33 |
| S7_sparse_reference | all | 3 | 45 | 0.311 | 0.000 [0.000, 1.000] | 14 | 31 | 14 | 550 [374, 1083] | 0.92 |
| S7_sparse_reference | all | 5 | 45 | 0.267 | 0.000 [0.000, 1.000] | 12 | 33 | 12 | 672 [237, 1018] | 0.50 |
| S7_sparse_reference | all | 10 | 45 | 0.222 | 0.000 [0.000, 0.000] | 10 | 35 | 10 | 1304 [1129, 1394] | 0.25 |
| S7_sparse_reference | all | 20 | 45 | 0.200 | 0.000 [0.000, 0.000] | 9 | 36 | 9 | 1696 [1129, 1697] | 0.17 |
| S7_sparse_reference | all | 50 | 45 | 0.067 | 0.000 [0.000, 0.000] | 3 | 42 | 3 | 1239 [1239, 1239] | 0.08 |

### Where recall crosses zero

- **S4_step_fault**: recall crosses zero between one reference in 20 and one in 50 -- located to within a factor of 2.5, which is the resolution of the rate ladder and not a property of the detector.
- **S7_sparse_reference**: recall is above zero at every rate run, down to one in 50. The crossing is sparser than this grid reaches.

The crossing is reported as a bracket because a bracket is what a ladder of rates can support. Interpolating a point inside it would assume a curve shape nothing here measures.

## A2 -- the governance effect against reference rate

Governed minus ungoverned over a byte-identical stream, **paired by seed**: the median of the per-seed differences, which is not the difference of the medians. Both are given so the two can be seen not to be the same number. Negative MAE is the loop helping.

**Signed bias travels beside the error and is never folded into it.** The loop can improve MAE while pushing the signed bias through zero and out the other side; a column of `|bias|` would show that as unambiguous improvement. `identical` counts the seeds whose two arms produced exactly the same MAE, which is what a median of 0.00 has to be read against.

| scenario | estimator | 1 in | pairs | identical | dMAE kg (IQR) | diff of medians | MAE gov | MAE open | dBias kg (IQR) | bias gov | bias open | recals |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| S4_step_fault | kalman | 1 | 15 | 1 | -0.19 [-1.40, 0.34] | +0.05 | 141.84 | 141.79 | 3.36 [-0.43, 5.09] | -2.32 | -3.80 | 1.0 |
| S4_step_fault | kalman | 2 | 15 | 8 | 0.00 [0.00, 0.17] | +0.00 | 144.50 | 144.50 | 0.00 [0.00, 5.68] | -3.49 | -8.21 | 0.0 |
| S4_step_fault | kalman | 3 | 15 | 2 | 0.06 [-0.16, 1.58] | +0.06 | 146.06 | 146.00 | -2.14 [-4.10, 3.64] | -9.63 | -7.80 | 1.0 |
| S4_step_fault | kalman | 5 | 15 | 6 | 0.00 [-0.65, 1.67] | +0.00 | 147.10 | 147.10 | 0.00 [0.00, 3.52] | -7.79 | -7.91 | 1.0 |
| S4_step_fault | kalman | 10 | 15 | 13 | 0.00 [0.00, 0.00] | +0.00 | 150.29 | 150.29 | 0.00 [0.00, 0.00] | -16.74 | -20.61 | 0.0 |
| S4_step_fault | kalman | 20 | 15 | 12 | 0.00 [0.00, 0.00] | +0.00 | 157.88 | 157.88 | 0.00 [0.00, 0.00] | -24.54 | -24.34 | 0.0 |
| S4_step_fault | kalman | 50 | 15 | 15 | 0.00 [0.00, 0.00] | +0.00 | 175.94 | 175.94 | 0.00 [0.00, 0.00] | -43.02 | -43.02 | 0.0 |
| S4_step_fault | rls | 1 | 15 | 3 | -0.20 [-0.60, 0.00] | +0.00 | 140.41 | 140.41 | 2.35 [0.18, 3.04] | -1.21 | -3.54 | 1.0 |
| S4_step_fault | rls | 2 | 15 | 3 | -0.36 [-0.93, 0.00] | -0.83 | 141.88 | 142.71 | 0.00 [-2.10, 5.17] | -8.08 | -8.65 | 1.0 |
| S4_step_fault | rls | 3 | 15 | 3 | -0.09 [-0.76, 0.00] | -0.75 | 144.45 | 145.20 | 4.69 [0.38, 9.35] | -7.61 | -11.62 | 1.0 |
| S4_step_fault | rls | 5 | 15 | 7 | 0.00 [-0.95, 0.00] | -0.61 | 146.81 | 147.42 | 0.00 [0.00, 17.52] | -10.39 | -18.37 | 1.0 |
| S4_step_fault | rls | 10 | 15 | 6 | 0.00 [0.00, 2.47] | +1.97 | 153.67 | 151.70 | 21.36 [0.00, 26.48] | -16.87 | -37.50 | 1.0 |
| S4_step_fault | rls | 20 | 15 | 12 | 0.00 [0.00, 0.00] | +0.08 | 161.40 | 161.32 | 0.00 [0.00, 0.00] | -62.84 | -62.84 | 0.0 |
| S4_step_fault | rls | 50 | 15 | 15 | 0.00 [0.00, 0.00] | +0.00 | 169.55 | 169.55 | 0.00 [0.00, 0.00] | -92.93 | -92.93 | 0.0 |
| S4_step_fault | static_affine | 1 | 15 | 2 | -40.34 [-42.31, -23.72] | -35.38 | 155.82 | 191.20 | 182.77 [136.28, 198.09] | +28.21 | -144.10 | 1.0 |
| S4_step_fault | static_affine | 2 | 15 | 0 | -33.38 [-40.38, -20.14] | -35.88 | 155.32 | 191.20 | 161.37 [115.16, 183.30] | +13.11 | -144.10 | 1.0 |
| S4_step_fault | static_affine | 3 | 15 | 3 | -31.43 [-42.87, -8.34] | -34.17 | 157.03 | 191.20 | 123.32 [107.07, 145.93] | -14.58 | -144.10 | 1.0 |
| S4_step_fault | static_affine | 5 | 15 | 4 | -8.37 [-26.05, 0.00] | -9.26 | 181.95 | 191.20 | 115.59 [11.76, 146.54] | -20.48 | -144.10 | 1.0 |
| S4_step_fault | static_affine | 10 | 15 | 1 | -8.63 [-14.42, 0.50] | -9.55 | 181.65 | 191.20 | 157.49 [146.01, 160.95] | +14.66 | -144.10 | 1.0 |
| S4_step_fault | static_affine | 20 | 15 | 11 | 0.00 [0.00, 0.00] | +0.86 | 192.06 | 191.20 | 0.00 [0.00, 3.51] | -138.23 | -144.10 | 0.0 |
| S4_step_fault | static_affine | 50 | 15 | 15 | 0.00 [0.00, 0.00] | +0.00 | 191.20 | 191.20 | 0.00 [0.00, 0.00] | -144.10 | -144.10 | 0.0 |
| S7_sparse_reference | kalman | 1 | 15 | 5 | 0.02 [0.00, 0.46] | +0.23 | 159.52 | 159.29 | -0.11 [-0.91, 0.00] | -5.74 | -5.17 | 1.0 |
| S7_sparse_reference | kalman | 2 | 15 | 12 | 0.00 [0.00, 0.00] | +0.78 | 160.52 | 159.74 | 0.00 [0.00, 0.00] | -8.21 | -7.78 | 0.0 |
| S7_sparse_reference | kalman | 3 | 15 | 10 | 0.00 [0.00, 0.22] | +0.63 | 160.87 | 160.25 | 0.00 [0.00, 0.00] | -8.59 | -8.59 | 0.0 |
| S7_sparse_reference | kalman | 5 | 15 | 12 | 0.00 [0.00, 0.00] | +0.15 | 161.81 | 161.66 | 0.00 [0.00, 0.00] | -14.53 | -14.53 | 0.0 |
| S7_sparse_reference | kalman | 10 | 15 | 14 | 0.00 [0.00, 0.00] | +0.00 | 162.60 | 162.60 | 0.00 [0.00, 0.00] | -20.65 | -20.65 | 0.0 |
| S7_sparse_reference | kalman | 20 | 15 | 14 | 0.00 [0.00, 0.00] | +0.00 | 167.06 | 167.06 | 0.00 [0.00, 0.00] | -26.60 | -28.23 | 0.0 |
| S7_sparse_reference | kalman | 50 | 15 | 15 | 0.00 [0.00, 0.00] | +0.00 | 173.84 | 173.84 | 0.00 [0.00, 0.00] | -49.15 | -49.15 | 0.0 |
| S7_sparse_reference | rls | 1 | 15 | 11 | 0.00 [0.00, 0.00] | +0.00 | 160.14 | 160.14 | 0.00 [0.00, 0.00] | -2.92 | -2.93 | 0.0 |
| S7_sparse_reference | rls | 2 | 15 | 8 | 0.00 [0.00, 0.02] | +0.00 | 160.24 | 160.24 | 0.00 [-0.05, 0.00] | -5.24 | -5.24 | 0.0 |
| S7_sparse_reference | rls | 3 | 15 | 12 | 0.00 [0.00, 0.00] | +0.00 | 160.19 | 160.19 | 0.00 [0.00, 0.00] | -8.41 | -8.41 | 0.0 |
| S7_sparse_reference | rls | 5 | 15 | 12 | 0.00 [0.00, 0.00] | +0.00 | 161.16 | 161.16 | 0.00 [0.00, 0.00] | -14.60 | -15.04 | 0.0 |
| S7_sparse_reference | rls | 10 | 15 | 14 | 0.00 [0.00, 0.00] | +0.00 | 162.23 | 162.23 | 0.00 [0.00, 0.00] | -28.20 | -28.20 | 0.0 |
| S7_sparse_reference | rls | 20 | 15 | 14 | 0.00 [0.00, 0.00] | -0.40 | 165.12 | 165.51 | 0.00 [0.00, 0.00] | -45.08 | -47.80 | 0.0 |
| S7_sparse_reference | rls | 50 | 15 | 15 | 0.00 [0.00, 0.00] | +0.00 | 172.89 | 172.89 | 0.00 [0.00, 0.00] | -76.01 | -76.01 | 0.0 |
| S7_sparse_reference | static_affine | 1 | 15 | 10 | 0.00 [-1.68, 0.00] | -4.06 | 181.74 | 185.79 | 0.00 [0.00, 0.82] | -85.53 | -96.70 | 0.0 |
| S7_sparse_reference | static_affine | 2 | 15 | 9 | 0.00 [-8.47, 0.00] | -5.00 | 180.80 | 185.79 | 0.00 [0.00, 37.92] | -77.86 | -96.70 | 0.0 |
| S7_sparse_reference | static_affine | 3 | 15 | 11 | 0.00 [-1.81, 0.00] | -3.77 | 182.02 | 185.79 | 0.00 [0.00, 0.00] | -84.62 | -96.70 | 0.0 |
| S7_sparse_reference | static_affine | 5 | 15 | 7 | 0.00 [-17.71, 0.00] | -6.79 | 179.01 | 185.79 | 0.00 [0.00, 53.87] | -56.38 | -96.70 | 1.0 |
| S7_sparse_reference | static_affine | 10 | 15 | 8 | 0.00 [-18.22, 0.00] | -7.40 | 178.39 | 185.79 | 0.00 [0.00, 50.05] | -59.37 | -96.70 | 0.0 |
| S7_sparse_reference | static_affine | 20 | 15 | 11 | 0.00 [0.00, 0.00] | -4.06 | 181.74 | 185.79 | 0.00 [0.00, 0.31] | -84.62 | -96.70 | 0.0 |
| S7_sparse_reference | static_affine | 50 | 15 | 15 | 0.00 [0.00, 0.00] | +0.00 | 185.79 | 185.79 | 0.00 [0.00, 0.00] | -96.70 | -96.70 | 0.0 |

