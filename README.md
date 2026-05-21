# Public Transport Accessibility Across Melbourne

FIT2179 Data Visualisation 2 project.

## Local preview

Open `index.html` with VS Code Live Server. The page uses Vega, Vega-Lite and Vega-Embed from CDN links, so an internet connection is needed for local preview.

## Data sources

- Public Transport Victoria GTFS and public transport spatial datasets supplied for the assignment.
- Australian Bureau of Statistics, Regional population 2024-25, data cube 32180DS0001.
- Australian Bureau of Statistics ASGS Edition 3 SA2 boundaries.

## Notes

Large raw files are intentionally excluded from the website. The page uses compact files in `data/processed`.

## Rebuilding processed data

The reproducible build script is in `scripts/build_fit2179_a2.py`. It reads the supplied raw transport and SA2 files from the local FIT2179 folder, joins ABS population data, creates compact processed files, and regenerates the Vega-Lite specs and webpage.
