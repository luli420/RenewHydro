# Evanger report and slides (A3.1.5 / D3.1.3)

Builds the Word report and the PowerPoint slides from the notebook outputs
(`notebooks/evanger_runoff_projections.ipynb` → `figures/` with `key_numbers.json`
and `summary_changes.csv`). Every number in the text comes from `key_numbers.json`.

```bash
npm install docx pptxgenjs react react-dom react-icons sharp
python make_basin_table.py <figures_dir> <aggregates_dir>
node build_report.js <figures_dir> Evanger_KiN2025_inflow_report.docx [package_info.json]
NODE_PATH=$PWD/node_modules node build_deck.js <figures_dir> Evanger_KiN2025_inflow_slides.pptx
```

`build_deck.js` uses `apply_theme.js` from the Claude pptx skill (path at the top of
the file) to write the theme colours; without it the deck still builds but keeps
Office's default palette.
