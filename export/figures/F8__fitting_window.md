# F8 — Fitting window against deployment conditions

**File:** `F8__fitting_window.png`  
**Data:** `export/data/F8_s2_seed1_trajectory.csv` (input trajectory).

**Statistic:** Descriptive, one run: histograms of sensor-body temperature; the run median and the window mean. No paired comparison is plotted.

**Sample:** S2_thermal_cycle, seed 1; plant grid at 50 Hz over 72 h; the window is the 60 calibration passes at 180 veh/h.

## Caption

The frozen arm is fitted on a 20.0-minute window whose mean sensor temperature is 7.53 °C, 7.05 °C below the deployment median of 14.59 °C. Temperature is not a model input: the model maps feature to mass, and temperature acts on the gain as a hidden variable. What the window misrepresents is therefore the conditional P(mass | feature), which depends on that hidden variable — an unrepresentative fitting sample, not a covariate shift. The window's gain is +0.146 % from the run median, +9.2 kg on the mean S2 vehicle (6,283 kg), carried as a bias because the fit is frozen.

## Notes

- The caption must not say 'covariate shift': the covariate (the feature) is not what moves.
- The previous version used a mean vehicle of 6 325 kg with no stored source; this one uses the S2 fleet mean from `export/data/vehicle_mass_by_scenario.csv`.
