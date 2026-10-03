# The reference-rate curve: reference_rate_ph75

Commit `6523c7de3aeb39be8cf014174993cd3408d7bdb3`. 180 runs. Rates run: 1 in 2, 1 in 5, 1 in 10, 1 in 20, 1 in 50.

## A1 -- detection recall against reference rate

**Governed arm only.** With the controller disabled the detectors are never constructed, so every ungoverned run in this sweep reports `alarms 0, detected 0, recall 0.000`. Those are structural zeros and pooling the two arms would halve every recall below while presenting 'the detector was not running' as 'the detector missed'.

Recall is `detected / (detected + missed)` over the calibration faults injected into the scenario, crediting only alarms that fired *after* a fault and within the scoring horizon. The mean is given as well as the median because recall over two or three injected faults takes a few discrete values, and a cell that plainly detected something can still have a median of 0.000. Detection delay is a median over the runs that detected anything at all; `n delay` says how many those were, and a run that detected nothing contributes no delay rather than a zero.

| scenario | estimator | 1 in | runs | recall mean | recall median (IQR) | hit | missed | n delay | delay s (IQR) | false alarms/h |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| S4_step_fault | kalman | 2 | 3 | 0.500 | 0.500 [0.500, 0.500] | 3 | 3 | 3 | 655 [599, 727] | 0.44 |
| S4_step_fault | kalman | 5 | 3 | 0.667 | 0.500 [0.500, 0.750] | 4 | 2 | 3 | 593 [580, 815] | 0.12 |
| S4_step_fault | kalman | 10 | 3 | 0.333 | 0.500 [0.250, 0.500] | 2 | 4 | 2 | 1067 [904, 1229] | 0.06 |
| S4_step_fault | kalman | 20 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 6 | 0 | -- | 0.06 |
| S4_step_fault | kalman | 50 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 6 | 0 | -- | 0.00 |
| S4_step_fault | rls | 2 | 3 | 0.667 | 0.500 [0.500, 0.750] | 4 | 2 | 3 | 408 [401, 476] | 0.44 |
| S4_step_fault | rls | 5 | 3 | 0.333 | 0.500 [0.250, 0.500] | 2 | 4 | 2 | 424 [339, 509] | 0.19 |
| S4_step_fault | rls | 10 | 3 | 0.333 | 0.500 [0.250, 0.500] | 2 | 4 | 2 | 1052 [987, 1116] | 0.06 |
| S4_step_fault | rls | 20 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 6 | 0 | -- | 0.06 |
| S4_step_fault | rls | 50 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 6 | 0 | -- | 0.00 |
| S4_step_fault | static_affine | 2 | 3 | 0.667 | 0.500 [0.500, 0.750] | 4 | 2 | 3 | 515 [483, 529] | 0.44 |
| S4_step_fault | static_affine | 5 | 3 | 0.333 | 0.000 [0.000, 0.500] | 2 | 4 | 1 | 566 [566, 566] | 0.19 |
| S4_step_fault | static_affine | 10 | 3 | 0.333 | 0.500 [0.250, 0.500] | 2 | 4 | 2 | 1123 [1095, 1152] | 0.06 |
| S4_step_fault | static_affine | 20 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 6 | 0 | -- | 0.06 |
| S4_step_fault | static_affine | 50 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 6 | 0 | -- | 0.00 |
| S4_step_fault | all | 2 | 9 | 0.611 | 0.500 [0.500, 0.500] | 11 | 7 | 9 | 544 [451, 544] | 0.44 |
| S4_step_fault | all | 5 | 9 | 0.444 | 0.500 [0.000, 0.500] | 8 | 10 | 6 | 580 [566, 593] | 0.19 |
| S4_step_fault | all | 10 | 9 | 0.333 | 0.500 [0.000, 0.500] | 6 | 12 | 6 | 1123 [959, 1181] | 0.06 |
| S4_step_fault | all | 20 | 9 | 0.000 | 0.000 [0.000, 0.000] | 0 | 18 | 0 | -- | 0.06 |
| S4_step_fault | all | 50 | 9 | 0.000 | 0.000 [0.000, 0.000] | 0 | 18 | 0 | -- | 0.00 |
| S7_sparse_reference | kalman | 2 | 3 | 1.000 | 1.000 [1.000, 1.000] | 3 | 0 | 3 | 678 [348, 1051] | 1.33 |
| S7_sparse_reference | kalman | 5 | 3 | 0.333 | 0.000 [0.000, 0.500] | 1 | 2 | 1 | 993 [993, 993] | 0.50 |
| S7_sparse_reference | kalman | 10 | 3 | 0.333 | 0.000 [0.000, 0.500] | 1 | 2 | 1 | 1424 [1424, 1424] | 0.17 |
| S7_sparse_reference | kalman | 20 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 3 | 0 | -- | 0.17 |
| S7_sparse_reference | kalman | 50 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 3 | 0 | -- | 0.08 |
| S7_sparse_reference | rls | 2 | 3 | 1.000 | 1.000 [1.000, 1.000] | 3 | 0 | 3 | 297 [158, 851] | 1.33 |
| S7_sparse_reference | rls | 5 | 3 | 0.333 | 0.000 [0.000, 0.500] | 1 | 2 | 1 | 993 [993, 993] | 0.50 |
| S7_sparse_reference | rls | 10 | 3 | 0.333 | 0.000 [0.000, 0.500] | 1 | 2 | 1 | 1424 [1424, 1424] | 0.17 |
| S7_sparse_reference | rls | 20 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 3 | 0 | -- | 0.17 |
| S7_sparse_reference | rls | 50 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 3 | 0 | -- | 0.08 |
| S7_sparse_reference | static_affine | 2 | 3 | 1.000 | 1.000 [1.000, 1.000] | 3 | 0 | 3 | 1406 [1140, 1413] | 1.25 |
| S7_sparse_reference | static_affine | 5 | 3 | 0.333 | 0.000 [0.000, 0.500] | 1 | 2 | 1 | 962 [962, 962] | 0.50 |
| S7_sparse_reference | static_affine | 10 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 3 | 0 | -- | 0.25 |
| S7_sparse_reference | static_affine | 20 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 3 | 0 | -- | 0.17 |
| S7_sparse_reference | static_affine | 50 | 3 | 0.000 | 0.000 [0.000, 0.000] | 0 | 3 | 0 | -- | 0.08 |
| S7_sparse_reference | all | 2 | 9 | 1.000 | 1.000 [1.000, 1.000] | 9 | 0 | 9 | 874 [297, 1406] | 1.33 |
| S7_sparse_reference | all | 5 | 9 | 0.333 | 0.000 [0.000, 1.000] | 3 | 6 | 3 | 993 [977, 993] | 0.50 |
| S7_sparse_reference | all | 10 | 9 | 0.222 | 0.000 [0.000, 0.000] | 2 | 7 | 2 | 1424 [1424, 1424] | 0.25 |
| S7_sparse_reference | all | 20 | 9 | 0.000 | 0.000 [0.000, 0.000] | 0 | 9 | 0 | -- | 0.17 |
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
| S4_step_fault | kalman | 2 | 3 | 2 | 0.00 [0.00, 0.33] | +0.65 | 138.30 | 137.65 | 0.00 [0.00, 0.14] | +1.70 | +1.70 | 0.0 |
| S4_step_fault | kalman | 5 | 3 | 1 | 0.00 [-1.51, 2.03] | -3.01 | 140.26 | 143.27 | 5.98 [2.99, 7.07] | -7.70 | -7.70 | 1.0 |
| S4_step_fault | kalman | 10 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 145.07 | 145.07 | 0.00 [0.00, 0.00] | -16.74 | -16.74 | 0.0 |
| S4_step_fault | kalman | 20 | 3 | 1 | 0.90 [0.45, 2.68] | +0.92 | 152.20 | 151.28 | 0.00 [-7.73, 2.93] | -24.54 | -24.54 | 1.0 |
| S4_step_fault | kalman | 50 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 156.26 | 156.26 | 0.00 [0.00, 0.00] | -42.48 | -42.48 | 0.0 |
| S4_step_fault | rls | 2 | 3 | 1 | -0.72 [-0.98, -0.36] | +0.00 | 135.56 | 135.56 | 0.00 [-2.30, 3.40] | -6.36 | -1.76 | 1.0 |
| S4_step_fault | rls | 5 | 3 | 1 | 0.00 [-1.59, 0.33] | -3.18 | 140.18 | 143.35 | 10.58 [5.29, 15.24] | -13.65 | -15.45 | 1.0 |
| S4_step_fault | rls | 10 | 3 | 1 | 1.72 [0.86, 3.39] | +3.90 | 151.38 | 147.48 | 22.05 [11.02, 29.77] | -4.26 | -40.95 | 1.0 |
| S4_step_fault | rls | 20 | 3 | 2 | 0.00 [0.00, 0.16] | +0.00 | 151.65 | 151.65 | 0.00 [-0.11, 0.00] | -62.84 | -62.84 | 0.0 |
| S4_step_fault | rls | 50 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 158.97 | 158.97 | 0.00 [0.00, 0.00] | -81.58 | -81.58 | 0.0 |
| S4_step_fault | static_affine | 2 | 3 | 0 | -40.51 [-43.90, -40.38] | -42.82 | 137.59 | 180.40 | 110.19 [103.43, 137.69] | -29.88 | -140.06 | 2.0 |
| S4_step_fault | static_affine | 5 | 3 | 1 | -29.97 [-33.56, -14.98] | -32.28 | 148.13 | 180.40 | 115.59 [57.79, 121.73] | -20.48 | -140.06 | 2.0 |
| S4_step_fault | static_affine | 10 | 3 | 0 | -3.08 [-5.86, -1.04] | -1.30 | 179.10 | 180.40 | 157.49 [156.47, 160.31] | +17.89 | -140.06 | 1.0 |
| S4_step_fault | static_affine | 20 | 3 | 2 | 0.00 [-1.32, 0.00] | +0.00 | 180.40 | 180.40 | 0.00 [0.00, 3.51] | -138.23 | -140.06 | 0.0 |
| S4_step_fault | static_affine | 50 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 180.40 | 180.40 | 0.00 [0.00, 0.00] | -140.06 | -140.06 | 0.0 |
| S7_sparse_reference | kalman | 2 | 3 | 2 | 0.00 [0.00, 0.39] | +0.00 | 159.20 | 159.20 | 0.00 [-0.42, 0.00] | -5.40 | -5.40 | 0.0 |
| S7_sparse_reference | kalman | 5 | 3 | 2 | 0.00 [0.00, 0.40] | +0.00 | 161.09 | 161.09 | 0.00 [0.00, 0.98] | -16.79 | -16.79 | 0.0 |
| S7_sparse_reference | kalman | 10 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 160.81 | 160.81 | 0.00 [0.00, 0.00] | -20.30 | -20.30 | 0.0 |
| S7_sparse_reference | kalman | 20 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 164.83 | 164.83 | 0.00 [0.00, 0.00] | -26.60 | -26.60 | 0.0 |
| S7_sparse_reference | kalman | 50 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 166.87 | 166.87 | 0.00 [0.00, 0.00] | -46.28 | -46.28 | 0.0 |
| S7_sparse_reference | rls | 2 | 3 | 2 | 0.00 [-0.02, 0.00] | -0.05 | 159.36 | 159.41 | 0.00 [-0.30, 0.00] | -4.08 | -4.08 | 0.0 |
| S7_sparse_reference | rls | 5 | 3 | 2 | 0.00 [-0.07, 0.00] | -0.15 | 160.67 | 160.82 | 0.00 [0.00, 1.65] | -12.80 | -15.98 | 0.0 |
| S7_sparse_reference | rls | 10 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 160.31 | 160.31 | 0.00 [0.00, 0.00] | -27.07 | -27.07 | 0.0 |
| S7_sparse_reference | rls | 20 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 162.67 | 162.67 | 0.00 [0.00, 0.00] | -44.60 | -44.60 | 0.0 |
| S7_sparse_reference | rls | 50 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 168.95 | 168.95 | 0.00 [0.00, 0.00] | -70.24 | -70.24 | 0.0 |
| S7_sparse_reference | static_affine | 2 | 3 | 2 | 0.00 [-8.80, 0.00] | -3.02 | 179.01 | 182.02 | 0.00 [0.00, 52.15] | -96.79 | -96.79 | 0.0 |
| S7_sparse_reference | static_affine | 5 | 3 | 2 | 0.00 [-8.94, 0.00] | -3.02 | 179.01 | 182.02 | 0.00 [0.00, 29.40] | -96.79 | -96.79 | 0.0 |
| S7_sparse_reference | static_affine | 10 | 3 | 1 | -17.62 [-18.22, -8.81] | -16.19 | 165.84 | 182.02 | 47.24 [23.62, 52.62] | -46.69 | -96.79 | 1.0 |
| S7_sparse_reference | static_affine | 20 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 182.02 | 182.02 | 0.00 [0.00, 0.00] | -96.79 | -96.79 | 0.0 |
| S7_sparse_reference | static_affine | 50 | 3 | 3 | 0.00 [0.00, 0.00] | +0.00 | 182.02 | 182.02 | 0.00 [0.00, 0.00] | -96.79 | -96.79 | 0.0 |

