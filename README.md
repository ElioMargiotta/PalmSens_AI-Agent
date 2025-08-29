# OCP Experiments — Plotting & Averaging

This repository/script processes **Open-Circuit Potential (OCP)** experiments organized as subfolders under a single root directory. Each experiment folder can contain multiple CSV files (replicates). For every experiment, the script:

1. **Overlays** all individual OCP curves.
2. **Resamples** all curves to a **common time grid**, computes the **mean** and **sample standard deviation**, and plots **mean ± 1σ**.
3. Saves the averaged data to `average.csv` and a small `manifest.json` per experiment.

---

## Directory layout

- The **root directory** is read from your `.env` file using the key `OCP_EXPERIMENTS_DIR`.  
  You can override it via the CLI flag `--root`.

```
<root>/
  experiment_A/
    run1.csv
    run2.csv
    ...
  experiment_B/
    sample1.csv
    sample2.csv
    ...
```

For each experiment folder, outputs are written under:

```
<experiment>/ocp_plots/
  overlay.png
  average.png
  average.csv       # time, mean, std, n_curves
  manifest.json
```

---

## How CSVs are parsed

- **Encodings:** The reader tries a BOM-based guess first (UTF-8/UTF-16 variants) and then falls back to common encodings (`utf-8-sig`, `utf-16*`, `cp1252`, `latin-1`).  
- **Delimiters & decimals:** It first lets pandas **sniff the delimiter** (`sep=None`, `engine="python"`). If nothing numeric is parsed, it retries with **decimal comma** (`decimal=","`).
- **Column selection (simplified):** We **do not use header names** anymore. The script simply takes the **first two numeric-looking columns**:
  - **First numeric column → time**
  - **Second numeric column → potential**

> If your CSV has an index in the first numeric column, please remove it or reorder columns so that **time** is first and **potential** is second.

- **Cleaning:** Non-numeric entries are coerced to `NaN` and dropped. Data are sorted by time; duplicate time stamps are removed (keep first).

---

## Resampling & Averaging, Mathematical details

Let there be `N` valid curves in one experiment. Curve `i` has samples $((t^{(i)}_j, y^{(i)}_j))$.

### 1) Common time grid

We only average over the **overlapping time range** across all curves:

- $( t_{\min} = \max_i \min_j \, t^{(i)}_j )$
- $( t_{\max} = \min_i \max_j \, t^{(i)}_j )$

If $( t_{\max} \le t_{\min} )$, averaging is skipped (non-overlapping time ranges).

The grid spacing `Δt` is chosen as the **largest median step** among all curves to avoid oversampling:

- For each curve, compute the median step $( \widetilde{\Delta t}^{(i)} = \mathrm{median}(\Delta t^{(i)}) )$ from consecutive time differences.
- $( \Delta t = \max_i \widetilde{\Delta t}^{(i)} )$ (fallback to `1.0` if unavailable or non-positive).

The number of grid points is:

- $( n = \max\!\left(2, \left\lfloor \frac{t_{\max} - t_{\min}}{\Delta t} \right\rfloor + 1 \right) )$

and the grid is the linear space:

- $( \{\, t_k \,\}_{k=0}^{n-1} = \mathrm{linspace}(t_{\min}, t_{\max}, n) )$

### 2) Interpolation

Each curve is **linearly interpolated** onto the common grid using `numpy.interp`:

- $( \hat{y}^{(i)}(t_k) = \mathrm{interp}(t_k;\; t^{(i)}, y^{(i)}) )$

Collecting all resampled curves gives a matrix $( Y \in \mathbb{R}^{N \times n} )$ with rows $( \hat{y}^{(i)} )$.

### 3) Mean and (sample) standard deviation

For each grid point \( t_k \), the **mean** is:

- $( \mu_k = \frac{1}{N} \sum_{i=1}^{N} \hat{y}^{(i)}(t_k) )$

The **sample standard deviation** (unbiased; `ddof=1`) is:

- $( s_k = \sqrt{ \frac{1}{N-1} \sum_{i=1}^{N} (\hat{y}^{(i)}(t_k) - \mu_k)^2 } )$, for $( N > 1 )$.  
  If $( N = 1 )$, we set $( s_k = 0 )$.

The plot `average.png` shows $( \mu_k )$(line) with the band $( \mu_k \pm s_k )$ (shaded).

---

## CLI usage

```bash
# Read root from .env (OCP_EXPERIMENTS_DIR)
python plot_ocp.py

# Or override the root directory explicitly
python plot_ocp.py --root "D:/data/ocp"
```

### .env

Create a `.env` next to the script (or in your working directory) with:

```
OCP_EXPERIMENTS_DIR=E:/lab/ocp_data
```

---

## Dependencies

- `pandas`
- `numpy`
- `matplotlib`
- `python-dotenv`
- ...

Install with:

```bash
pip install -r requirements.txt
```

---

## Outputs in detail

- **overlay.png** — all raw curves plotted together (legend is placed outside the axes).
- **average.png** — resampled **mean ± 1σ** on the common grid.
- **average.csv** — columns: `time, mean, std, n_curves`.
- **manifest.json** — per-experiment metadata:
  - experiment name, root path, number of CSVs, list of used files
  - relative paths to the plots/CSV
  - errors encountered while loading curves

---

## Assumptions & limitations

- **Column selection is purely positional** (first two numeric columns). If the wrong columns are selected (e.g., an index comes first), **reorder your CSV** so that *time* is the first numeric column and *potential* is the second.
- Averaging requires **overlapping time ranges** across curves.
- Interpolation is **linear**; if your data require higher-order interpolation or smoothing, adapt `resample_to_grid` accordingly.
- Sample standard deviation uses `ddof=1`. For population std, change to `ddof=0`.

---

## Troubleshooting

- **"Root directory not found"** — set `OCP_EXPERIMENTS_DIR` in `.env` or pass `--root`.
- **"No valid numeric data"** — check CSV encoding/delimiter/decimal; ensure the first two meaningful columns are numeric.
- **"Time ranges do not overlap"** — your replicates start/stop at very different times. Trim or pre-align them.
- **Strange overlay shapes** — verify time sorting and duplicate timestamps (the script removes exact duplicates).

---

## Implementation notes

- Legend is drawn outside the axes to avoid layout issues.
- The common-grid `Δt` selection avoids overly dense grids that can exaggerate noise.
- Encoding handling tries several common code pages and BOMs for robustness.

---