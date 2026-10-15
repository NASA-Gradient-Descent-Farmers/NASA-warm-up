# NASA Space Apps & Agronomic Intelligence Warm-up 🛰️🌾
Suck it bro
**Note:** I used the Colab extension in VSCode to run, download and interact with the data, so the datasets will not be found in this repository since they are referenced using the ```earthaccess``` library from **NASA**. Note that you need to register in order to pull the data into your workspace.

> **Central Source of Truth (SoT)** for our team's data science warm-up applications, Earth observation pipelines, agronomic models, and literature exploration.

![Team Banner](Images/team_image.jpeg)

---

## 🎯 Purpose & Scope

The goal of this repository is to serve as the unified workspace and launchpad for exploring agricultural datasets, remote sensing products, and decision-support modeling.

We use this repo to:

* **Gain hands-on experience** querying, downloading, and preprocessing satellite observations (SMAP, MODIS, Landsat/Sentinel).
* **Engineer predictive agronomic features** (e.g., continuous soil moisture dynamics, drought indexes, root-zone depletion rates).
* **Benchmark decision-support tools & models** to aid long-term strategic decision making at the cropping system level, rather than just short-term tactical decisions for individual crops[cite: 2].
* **Maintain a shared literature & knowledge base** across the team.

---

## 📁 Repository Structure

```text
├── Articles/           # Key papers, benchmark studies, and crop modeling literature
├── data/               # Ignored directory for bulky raw Earth observation files (.h5, .nc, .tif)
├── dashboard/          # Front-end React/Python assets for the interactive decision-support tool
├── Images/             # Visuals, team assets, and generated figures
├── Notebooks/          # Exploratory analysis, pipelines, and prototyping notebooks
│   ├── sample_SMAP.ipynb
│   ├── sample_MODIS.ipynb
│   └── sample_POWER.ipynb
├── src/                # Modularized Python utility functions and data ingestion scripts
├── .gitignore          # Configured to ignore bulky raw data, caches, and environment files
├── requirements.txt    # Unified dependencies for team environment reproducibility
├── LICENSE
└── README.md           # This document (Source of Truth)

```

---

## 🚀 Getting Started

### 1. Environment Setup

Clone the repository and set up a unified Python virtual environment using the shared requirements:

```bash
git clone https://github.com/danielmalvaez/NASA-warm-up.git
cd NASA-warm-up

python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt ## we are missing the requirements txt.

```

### 2. NASA Earthdata Login Credentials

Accessing NASA DAAC datasets via `earthaccess` requires an Earthdata account:

1. Register for free at NASA Earthdata Login.
2. Authenticate interactively or via `.netrc`:
```python
import earthaccess
auth = earthaccess.login(strategy="interactive", persist=True)

```



---

## 🧪 Modules & Explorations

### 🛰️ SMAP Soil Moisture Pipeline (`Notebooks/sample_SMAP.ipynb`)

* **Product**: `SPL4SMGP` (SMAP L4 Global 3-hourly 9 km Surface and Root-Zone Soil Moisture).
* **Capabilities**:
* Spatial bounding-box query and download using `earthaccess`.
* HDF5 (`.h5`) inspection and multi-band extraction via `h5py`.
* Measuring the moisture lodged in Earth's soils with an unprecedented accuracy and resolution[cite: 5].
* Extracting continuous time series:
* **Surface Soil Moisture (`sm_surface`)**: $0 - 5\text{ cm}$, rapid evaporation & infiltration.
* **Root-Zone Soil Moisture (`sm_rootzone`)**: $0 - 100\text{ cm}$, crop water reservoir & drought resilience.





### 🛰️ MODIS Vegetation Pipeline (`Notebooks/sample_MODIS.ipynb`)

* **Purpose**: High-temporal-resolution extraction of Normalized Difference Vegetation Index (NDVI) and Leaf Area Index (LAI).
* **Capabilities**: Processes raw satellite imagery to capture spatial field heterogeneity, acting as the primary visual state representation for crop health.

### 🌤️ POWER Meteorological Pipeline (`Notebooks/sample_POWER.ipynb`)

* **Purpose**: Ingestion of tabular, analysis-ready historical climate sequences (solar radiation, temperatures, precipitation).
* **Capabilities**: Feeds the stochastic environmental transitions into our RL models to ensure resilience against extreme climate events.
* **Ingestion script**: `src/data_ingestion/power.py` pulls daily point data (AG community) from the POWER API, tests the connection and previews records: `python -m src.data_ingestion.power --lat 42.03 --lon -93.47 --start 20240101 --end 20240131`.

### 📥 Data Ingestion (`src/data_ingestion/`)

* One script per source (POWER, SMAP L4, GLDAS soils, IGBP-DIS soils). Each tests the connection, pulls data and previews 5 records. See [`src/data_ingestion/README.md`](src/data_ingestion/README.md) for setup (including the Earthdata login), usage and per-source notes.

### 🌱 Crop Rotations (`src/crop_models/`)

* Simulates seasonal crop rotations (e.g. maize, maize-barley, maize-faba bean) for rainfed farms in central Mexico with the WOFOST 8.1 crop model (PCSE): water, nitrogen, frost, rain-onset sowing, drought indicators and drier-climate scenarios, driven by POWER weather and GLDAS/IGBP soils, and checked against SMAP. See [`src/crop_models/README.md`](src/crop_models/README.md).
* Technical report (LaTeX) with data, equations, assumptions and results: [`docs/technical_report/`](docs/technical_report/).

### ⚖️ Economic Proxy Metrics & MOO (`src/moo_reward.py`)

* **Purpose**: Balances competing metrics to generate Pareto frontiers without relying on complex, highly variable external financial APIs.
* **Function**: Translates large-scale agricultural simulation outputs into actionable on-farm decisions[cite: 2]. It utilizes fixed heuristic coefficients (e.g., relative yield pricing, water-use efficiency) to represent financial returns within the RL reward function.

---

## 📚 Literature Base (`Articles/`)

Curated research foundational to our solution architecture:

* **Crop Modeling & Simulators**: Evaluating cropping systems using the APSIM simulation database[cite: 2, 7].
* **Reinforcement Learning**: CYCLESGYM is an RL environment based on the multi-year, multi-crop CGM Cycles that allows for long-term planning in agroecosystems[cite: 4].
* **Machine Learning Classifiers**: Developing decision support systems utilizing algorithms like Random Forest and Extreme Gradient Boosting[cite: 3].
* **Cloud Architecture**: Utilizing Firebase cloud memory for storing structured datasets and bridging predictive models to user-facing applications[cite: 3].

---

## 🤝 Team Contribution Guidelines (SoT Best Practices)

To keep this repository clean, reproducible, and easy to build on:

1. **Never commit large raw data files (`.h5`, `.nc`, `.tif`, `.csv` > 50MB)**:
* Keep downloads inside the local ignored `data/` directory.
* Write reproducible download scripts or caching checks rather than pushing binaries.


2. **Clear Notebook Outputs Before Committing**:
* Strip heavy widget states or intermediate printouts before pushing to Git (`Kernel -> Clear All Outputs`).


3. **Modularize & Format Code**:
* If a utility or transformation function is reused across multiple notebooks, extract it into a dedicated Python module in `src/`.
* Run a standard linter/formatter (like `black` or `ruff`) on all Python scripts before opening a Pull Request.


4. **Document New Experiments**:
* When adding a notebook or new paper, add a 1-line note in the module summary of this README.
