# Technical report (LaTeX)

`main.tex` documents the data pipeline, the crop model equations, the Mexican-context additions, the assumptions and the results. Tables in `tables/` are generated from the simulations, so the numbers always match the data.

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
