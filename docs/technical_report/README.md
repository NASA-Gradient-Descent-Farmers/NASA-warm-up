# Technical report (LaTeX)

`main.tex` documents the data pipeline, the crop model equations, the Mexican-context additions, the assumptions and the results. Two companions: `wofost_primer.tex` explains what kind of model WOFOST is, and `calibration.tex` explains, step by step, how the model was calibrated to Texcoco farm yields (SIAP). Tables in `tables/` are generated from the simulations, so the numbers always match the data.

## Build the PDF

- **Overleaf**: upload `main.tex`, `references.bib` and the `tables/` folder, and compile with pdfLaTeX.
- **Locally**: install a TeX engine (for example `brew install tectonic`), then from this folder:

  ```bash
  tectonic main.tex
  ```

## Update the numbers

Rerun the simulations (commands in the report's Reproducibility section, saved under `data/rotations/`), then from the repo root:

```bash
python docs/technical_report/make_tables.py
```

The calibration figures come from the calibrated runs in `data/rotations_calibrated/` (see `calibration.tex`, section 10):

```bash
python docs/technical_report/make_calibration_figures.py
```
