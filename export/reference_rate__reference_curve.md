# The reference-rate curve: reference_rate

Commit `c1881d4f6c0f31cc50171d6c3004faa1325b5e8d`. 180 runs. Rates run: 1 in 2, 1 in 5, 1 in 10, 1 in 20, 1 in 50.

## A1 -- detection recall against reference rate

**Governed arm only.** With the controller disabled the detectors are never constructed, so every ungoverned run in this sweep reports `alarms 0, detected 0, recall 0.000`. Those are structural zeros and pooling the two arms would halve every recall below while presenting 'the detector was not running' as 'the detector missed'.

Recall is `detected / (detected + missed)` over the calibration faults injected into the scenario, crediting only alarms that fired *after* a fault and within the scoring horizon. The mean is given as well as the median because recall over two or three injected faults takes a few discrete values, and a cell that plainly detected something can still have a median of 0.000. Detection delay is a median over the runs that detected anything at all; `n delay` says how many those were, and a run that detected nothing contributes no delay rather than a zero.

| scenario | estimator | 1 in | runs | recall mean | recall median (IQR) | hit | missed | n delay | delay s (IQR) | false alarms/h |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| S4_step_fault | kalman | 2 | 3 | 0.667 | 0.500 [0.500, 0.750] | 4 | 2 | 3 | 421 [325, 456] | 0.25 |
| S4_step_fault | kalman | 5 | 3 | 0.500 | 0.500 [0.500, 0.500] | 3 | 3 | 3 | 1308 [1025, 1357] | 0.06 |
| S4_step_fault | kalman | 10 | 3 | 0.167 | 0.000 [0.000, 0.250] | 1 | 5 | 1 | 1391 [1391, 1391] | 0.06 |
| S4_step_fault | kalman | 20 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 6 | 0 | -- | 0.06 |
| S4_step_fault | kalman | 50 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 6 | 0 | -- | 0.00 |
| S4_step_fault | rls | 2 | 3 | 0.667 | 0.500 [0.500, 0.750] | 4 | 2 | 3 | 544 [310, 639] | 0.19 |
| S4_step_fault | rls | 5 | 3 | 0.500 | 0.500 [0.500, 0.500] | 3 | 3 | 3 | 1236 [989, 1272] | 0.06 |
| S4_step_fault | rls | 10 | 3 | 0.167 | 0.000 [0.000, 0.250] | 1 | 5 | 1 | 1391 [1391, 1391] | 0.06 |
| S4_step_fault | rls | 20 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 6 | 0 | -- | 0.06 |
| S4_step_fault | rls | 50 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 6 | 0 | -- | 0.00 |
| S4_step_fault | static_affine | 2 | 3 | 0.667 | 0.500 [0.500, 0.750] | 4 | 2 | 3 | 580 [541, 654] | 0.19 |
| S4_step_fault | static_affine | 5 | 3 | 0.667 | 0.500 [0.500, 0.750] | 4 | 2 | 3 | 972 [857, 1140] | 0.12 |
| S4_step_fault | static_affine | 10 | 3 | 0.167 | 0.000 [0.000, 0.250] | 1 | 5 | 1 | 1391 [1391, 1391] | 0.12 |
| S4_step_fault | static_affine | 20 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 6 | 0 | -- | 0.06 |
| S4_step_fault | static_affine | 50 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 6 | 0 | -- | 0.00 |
| S4_step_fault | all | 2 | 9 | 0.667 | 0.500 [0.500, 1.000] | 12 | 6 | 9 | 503 [421, 580] | 0.19 |
| S4_step_fault | all | 5 | 9 | 0.556 | 0.500 [0.500, 0.500] | 10 | 8 | 9 | 1236 [742, 1308] | 0.06 |
| S4_step_fault | all | 10 | 9 | 0.167 | 0.000 [0.000, 0.500] | 3 | 15 | 3 | 1391 [1391, 1391] | 0.06 |
| S4_step_fault | all | 20 | 9 | 0.000 | 0.000 [0.000, 0.000] | 0 | 18 | 0 | -- | 0.06 |
| S4_step_fault | all | 50 | 9 | 0.000 | 0.000 [0.000, 0.000] | 0 | 18 | 0 | -- | 0.00 |
| S7_sparse_reference | kalman | 2 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 3 | 0 | -- | 0.50 |
| S7_sparse_reference | kalman | 5 | 3 | 0.333 | 0.000 [0.000, 0.500] | 1 | 2 | 1 | 749 [749, 749] | 0.25 |
| S7_sparse_reference | kalman | 10 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 3 | 0 | -- | 0.00 |
| S7_sparse_reference | kalman | 20 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 3 | 0 | -- | 0.08 |
| S7_sparse_reference | kalman | 50 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 3 | 0 | -- | 0.08 |
| S7_sparse_reference | rls | 2 | 3 | 0.333 | 0.000 [0.000, 0.500] | 1 | 2 | 1 | 1522 [1522, 1522] | 0.42 |
| S7_sparse_reference | rls | 5 | 3 | 0.667 | 1.000 [0.500, 1.000] | 2 | 1 | 2 | 1166 [958, 1375] | 0.25 |
| S7_sparse_reference | rls | 10 | 3 | 0.333 | 0.000 [0.000, 0.500] | 1 | 2 | 1 | 509 [509, 509] | 0.08 |
| S7_sparse_reference | rls | 20 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 3 | 0 | -- | 0.08 |
| S7_sparse_reference | rls | 50 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 3 | 0 | -- | 0.08 |
| S7_sparse_reference | static_affine | 2 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 3 | 0 | -- | 0.92 |
| S7_sparse_reference | static_affine | 5 | 3 | 0.333 | 0.000 [0.000, 0.500] | 1 | 2 | 1 | 749 [749, 749] | 0.25 |
| S7_sparse_reference | static_affine | 10 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 3 | 0 | -- | 0.17 |
| S7_sparse_reference | static_affine | 20 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 3 | 0 | -- | 0.08 |
| S7_sparse_reference | static_affine | 50 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 3 | 0 | -- | 0.08 |
| S7_sparse_reference | all | 2 | 9 | 0.111 | 0.000 [0.000, 0.000] | 1 | 8 | 1 | 1522 [1522, 1522] | 0.50 |
| S7_sparse_reference | all | 5 | 9 | 0.444 | 0.000 [0.000, 1.000] | 4 | 5 | 4 | 749 [749, 958] | 0.25 |
| S7_sparse_reference | all | 10 | 9 | 0.111 | 0.000 [0.000, 0.000] | 1 | 8 | 1 | 509 [509, 509] | 0.08 |
| S7_sparse_reference | all | 20 | 9 | 0.000 | 0.000 [0.000, 0.000] | 0 | 9 | 0 | -- | 0.08 |
| S7_sparse_reference | all | 50 | 9 | 0.000 | 0.000 [0.000, 0.000] | 0 | 9 | 0 | -- | 0.08 |

### Where recall crosses zero

- **S4_step_fault**: recall crosses zero between one reference in 10 and one in 20 -- located to within a factor of 2, which is the resolution of the rate ladder and not a property of the detector.
- **S7_sparse_reference**: recall crosses zero between one reference in 10 and one in 20 -- located to within a factor of 2, which is the resolution of the rate ladder and not a property of the detector.

The crossing is reported as a bracket because a bracket is what a ladder of rates can support. Interpolating a point inside it would assume a curve shape nothing here measures.

## A2 -- the governance effect against reference rate

Governed minus ungoverned over a byte-identical stream, **paired by seed**: the median of the per-seed differences, which is not the difference of the medians. Both are given so the two can be seen not to be the same number. Negative MAE is the loop helping.

**Signed bias travels beside the error and is never folded into it.** The loop can improve MAE while pushing the signed bias through zero and out the other side; a column of `|bias|` would show that as unambiguous improvement. `identical` counts the seeds whose two arms produced exactly the same MAE, which is what a median of 0.00 has to be read against.

| scenario | estimator | 1 in | pairs | identical | dMAE kg (IQR) | diff of medians | MAE gov | MAE open | dBias kg (IQR) | bias gov | bias open | recals |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| S4_step_fault | kalman | 2 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 137.65 | 137.65 | 0.00 [0.00, 0.00] | +1.70 | +1.70 | 0.0 |
| S4_step_fault | kalman | 5 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 143.27 | 143.27 | 0.00 [0.00, 0.00] | -7.70 | -7.70 | 0.0 |
| S4_step_fault | kalman | 10 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 145.07 | 145.07 | 0.00 [0.00, 0.00] | -16.74 | -16.74 | 0.0 |
| S4_step_fault | kalman | 20 | 3 | 2 | 0.00 [0.00, 0.39] | +0.79 | 152.07 | 151.28 | 0.00 [-0.40, 0.00] | -24.54 | -24.54 | 0.0 |
| S4_step_fault | kalman | 50 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 156.26 | 156.26 | 0.00 [0.00, 0.00] | -42.48 | -42.48 | 0.0 |
| S4_step_fault | rls | 2 | 3 | 2 | 0.00 [0.00, 0.01] | +0.00 | 135.56 | 135.56 | 0.00 [-3.03, 0.00] | -7.38 | -1.76 | 0.0 |
| S4_step_fault | rls | 5 | 3 | 1 | 0.60 [0.30, 0.88] | +0.00 | 143.35 | 143.35 | 10.27 [5.13, 17.06] | +8.40 | -15.45 | 1.0 |
| S4_step_fault | rls | 10 | 3 | 1 | 2.53 [1.26, 4.46] | +5.22 | 152.71 | 147.48 | 23.06 [11.53, 28.02] | -8.78 | -40.95 | 1.0 |
| S4_step_fault | rls | 20 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 151.65 | 151.65 | 0.00 [0.00, 0.00] | -62.84 | -62.84 | 0.0 |
| S4_step_fault | rls | 50 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 158.97 | 158.97 | 0.00 [0.00, 0.00] | -81.58 | -81.58 | 0.0 |
| S4_step_fault | static_affine | 2 | 3 | 0 | -32.38 [-35.24, -23.20] | -22.92 | 157.48 | 180.40 | 180.98 [163.02, 187.04] | +40.92 | -140.06 | 1.0 |
| S4_step_fault | static_affine | 5 | 3 | 0 | -4.31 [-12.35, 1.21] | -6.62 | 173.78 | 180.40 | 181.26 [175.95, 210.36] | +45.19 | -140.06 | 1.0 |
| S4_step_fault | static_affine | 10 | 3 | 0 | -1.80 [-5.38, 1.30] | +2.09 | 182.49 | 180.40 | 156.50 [155.64, 158.02] | +16.44 | -140.06 | 1.0 |
| S4_step_fault | static_affine | 20 | 3 | 2 | 0.00 [-1.32, 0.00] | +0.00 | 180.40 | 180.40 | 0.00 [0.00, 3.51] | -138.23 | -140.06 | 0.0 |
| S4_step_fault | static_affine | 50 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 180.40 | 180.40 | 0.00 [0.00, 0.00] | -140.06 | -140.06 | 0.0 |
| S7_sparse_reference | kalman | 2 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 159.20 | 159.20 | 0.00 [0.00, 0.00] | -5.40 | -5.40 | 0.0 |
| S7_sparse_reference | kalman | 5 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 161.09 | 161.09 | 0.00 [0.00, 0.00] | -16.79 | -16.79 | 0.0 |
| S7_sparse_reference | kalman | 10 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 160.81 | 160.81 | 0.00 [0.00, 0.00] | -20.30 | -20.30 | 0.0 |
| S7_sparse_reference | kalman | 20 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 164.83 | 164.83 | 0.00 [0.00, 0.00] | -26.60 | -26.60 | 0.0 |
| S7_sparse_reference | kalman | 50 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 166.87 | 166.87 | 0.00 [0.00, 0.00] | -46.28 | -46.28 | 0.0 |
| S7_sparse_reference | rls | 2 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 159.41 | 159.41 | 0.00 [0.00, 0.00] | -4.08 | -4.08 | 0.0 |
| S7_sparse_reference | rls | 5 | 3 | 2 | 0.00 [-0.17, 0.00] | -0.34 | 160.48 | 160.82 | 0.00 [0.00, 1.69] | -12.80 | -15.98 | 0.0 |
| S7_sparse_reference | rls | 10 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 160.31 | 160.31 | 0.00 [0.00, 0.00] | -27.07 | -27.07 | 0.0 |
| S7_sparse_reference | rls | 20 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 162.67 | 162.67 | 0.00 [0.00, 0.00] | -44.60 | -44.60 | 0.0 |
| S7_sparse_reference | rls | 50 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 168.95 | 168.95 | 0.00 [0.00, 0.00] | -70.24 | -70.24 | 0.0 |
| S7_sparse_reference | static_affine | 2 | 3 | 2 | 0.00 [-7.16, 0.00] | -3.02 | 179.01 | 182.02 | 0.00 [0.00, 30.14] | -96.79 | -96.79 | 0.0 |
| S7_sparse_reference | static_affine | 5 | 3 | 2 | 0.00 [-9.49, 0.00] | -3.02 | 179.01 | 182.02 | 0.00 [0.00, 35.85] | -96.79 | -96.79 | 0.0 |
| S7_sparse_reference | static_affine | 10 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 182.02 | 182.02 | 0.00 [0.00, 0.00] | -96.79 | -96.79 | 0.0 |
| S7_sparse_reference | static_affine | 20 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 182.02 | 182.02 | 0.00 [0.00, 0.00] | -96.79 | -96.79 | 0.0 |
| S7_sparse_reference | static_affine | 50 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 182.02 | 182.02 | 0.00 [0.00, 0.00] | -96.79 | -96.79 | 0.0 |

