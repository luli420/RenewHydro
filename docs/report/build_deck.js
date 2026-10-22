// Build the Evanger KiN2025 inflow slides from the notebook outputs.
// Usage: node build_deck.js <figures_dir> <out.pptx>
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const md = require("react-icons/md");
const { applyTheme } = require("/Users/luli/.claude/skills/synced/4fce688b-7f99-4144-a6c9-8f80fc7eec2f_00093f3a-7e7a-481b-9df9-6ec4f5d0dff2/pptx/scripts/apply_theme.js");

const FIG = process.argv[2];
const OUT = process.argv[3];
const K = JSON.parse(fs.readFileSync(path.join(FIG, "key_numbers.json"), "utf8"));
const NEAR = "Near 2041–2070", FAR = "Far 2071–2100";

const THEME = {
  name: "Fjord", headFontFace: "Cambria", bodyFontFace: "Calibri",
  colors: { dk1: "0E2A3B", lt1: "FFFFFF", dk2: "1B6F8A", lt2: "EAF2F5",
    accent1: "1B6F8A", accent2: "D55E00", accent3: "E69F00", accent4: "0072B2", accent5: "5A6B75", accent6: "7FB7BE",
    hlink: "1B6F8A", folHlink: "5A6B75" },
};
const HEX = THEME.colors;

const sgn = (v, d = 0) => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(d);
const m = (block, s, p, d = 0) => sgn(block[`${s}|${p}`].median, d);

async function icon(Comp, color) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color: "#" + color, size: 256 }));
  const png = await sharp(Buffer.from(svg)).resize(256, 256).png().toBuffer();
  return "image/png;base64," + png.toString("base64");
}

function pngSize(file) {
  const b = fs.readFileSync(file);
  return [b.readUInt32BE(16), b.readUInt32BE(20)];
}
// place a figure inside a box, keeping its aspect ratio
function addFigure(slide, file, box, name) {
  const p = path.join(FIG, file);
  const [w, h] = pngSize(p);
  let W = box.w, H = (box.w * h) / w;
  if (H > box.h) { H = box.h; W = (box.h * w) / h; }
  slide.addImage({ path: p, x: box.x + (box.w - W) / 2, y: box.y + (box.h - H) / 2, w: W, h: H, objectName: name,
    altText: name });
}

(async () => {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5 in
  pres.author = "Lu Li (NORCE)";
  pres.company = "NORCE";
  pres.title = "Climate change and inflow to the Evanger hydropower system";
  pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
  const C = pres.SchemeColor;

  // ---------- layouts ----------
  pres.defineSlideMaster({
    title: "TITLE_DARK", background: { color: HEX.dk1 },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 2.0, w: 11.7, h: 1.8, fontSize: 40, bold: true, color: C.background1, valign: "bottom" }, text: "" } },
      { placeholder: { options: { name: "body", type: "body", x: 0.8, y: 4.0, w: 11.7, h: 1.6, fontSize: 20, color: C.accent6, valign: "top" }, text: "" } },
    ],
  });
  pres.defineSlideMaster({
    title: "CLOSING_DARK", background: { color: HEX.dk1 },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 0.5, w: 11.7, h: 0.9, fontSize: 34, bold: true, color: C.background1, valign: "middle" }, text: "" } },
    ],
  });
  pres.defineSlideMaster({
    title: "CONTENT", background: { color: HEX.lt1 },
    margin: [0.4, 0.6, 0.6, 0.6],
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.35, w: 12.1, h: 0.85, fontSize: 30, bold: true, color: C.text1, valign: "middle" }, text: "" } },
      { text: { text: "RenewHydro · Evanger inflow projections (KiN2025)", options: { x: 0.6, y: 7.0, w: 8, h: 0.3, fontSize: 10, color: C.accent5 } } },
    ],
    slideNumber: { x: 12.2, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: HEX.accent5 },
  });

  const ic = {
    map: await icon(md.MdMap, HEX.accent1), grid: await icon(md.MdGridOn, HEX.accent1), models: await icon(md.MdStackedLineChart, HEX.accent1),
    files: await icon(md.MdCloudDownload, HEX.accent1), cal: await icon(md.MdDateRange, HEX.accent1),
    winter: await icon(md.MdAcUnit, HEX.lt1), drop: await icon(md.MdWaterDrop, HEX.lt1), flood: await icon(md.MdWaves, HEX.lt1),
    bolt: await icon(md.MdBolt, HEX.lt1), sun: await icon(md.MdWbSunny, HEX.lt1),
  };

  const takeaway = (slide, x, y, w, h, big, text, color = C.accent1, name = "takeaway") => {
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: C.background2 }, line: { type: "none" }, rectRadius: 0.12, objectName: name + "-card" });
    const runs = [];
    if (big) runs.push({ text: big, options: { fontSize: big.length > 8 ? 28 : 36, bold: true, color, breakLine: true, fontFace: "Cambria" } });
    runs.push({ text, options: { fontSize: 16, color: C.text1 } });
    slide.addText(runs, { x: x + 0.25, y: y + 0.2, w: w - 0.5, h: h - 0.4, valign: "top", isTextBox: true, margin: 0, paraSpaceAfter: 6, objectName: name + "-text" });
  };
  const figSlide = (section, title, file, big, text, notes, color) => {
    const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: section });
    s.addText(title, { placeholder: "title" });
    addFigure(s, file, { x: 0.6, y: 1.35, w: 8.7, h: 5.45 }, file);
    takeaway(s, 9.6, 1.45, 3.13, 3.6, big, text, color);
    s.addNotes(notes);
    return s;
  };

  // ---------- 1. title ----------
  pres.addSection({ title: "Introduction" });
  let s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Introduction" });
  s.addText("Climate change and inflow to the Evanger hydropower system", { placeholder: "title" });
  s.addText([
    { text: `KiN2025 runoff projections for ${K.n_basins} sub-catchments, 1971–2100`, options: { breakLine: true } },
    { text: "RenewHydro WP3 · A3.1.3, A3.1.5, D3.1.3 · Lu Li, NORCE · October 2026", options: { fontSize: 16, color: C.background2 } },
  ], { placeholder: "body" });
  s.addNotes("Climate-change inflow analysis for the Evanger user case (Eviny), RenewHydro WP3 tasks A3.1.3 and A3.1.5, and deliverable D3.1.3 (data on NIRD).");

  // ---------- 2. key messages ----------
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Introduction" });
  s.addText("Less change in the annual total, much more in the seasons", { placeholder: "title" });
  const stats = [
    [m(K.annual, "ssp370", FAR) + " %", "annual inflow", `rcp26 ${m(K.annual, "rcp26", FAR)} % · rcp45 ${m(K.annual, "rcp45", FAR)} %`, C.accent1, ic.drop],
    [m(K.seasons["DJF_%"], "ssp370", FAR) + " %", "winter (Dec–Feb)", `rcp26 ${m(K.seasons["DJF_%"], "rcp26", FAR)} % · rcp45 ${m(K.seasons["DJF_%"], "rcp45", FAR)} %`, C.accent4, ic.winter],
    [m(K.seasons["JJA_%"], "ssp370", FAR) + " %", "summer (Jun–Aug)", `rcp26 ${m(K.seasons["JJA_%"], "rcp26", FAR)} % · rcp45 ${m(K.seasons["JJA_%"], "rcp45", FAR)} %`, C.accent2, ic.sun],
    [Math.abs(K.cov_shift_days["ssp370|" + FAR].median).toFixed(0) + " days", "earlier centre of volume", `rcp26 ${Math.abs(K.cov_shift_days["rcp26|" + FAR].median).toFixed(0)} · rcp45 ${Math.abs(K.cov_shift_days["rcp45|" + FAR].median).toFixed(0)} days`, C.accent3, ic.cal],
  ];
  stats.forEach(([big, label, sub, color, img], i) => {
    const x = 0.6 + i * 3.1;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.6, w: 2.85, h: 3.3, fill: { color: C.background2 }, line: { type: "none" }, rectRadius: 0.12, objectName: `stat${i}-card` });
    s.addShape(pres.shapes.OVAL, { x: x + 0.25, y: 1.85, w: 0.7, h: 0.7, fill: { color }, line: { type: "none" }, objectName: `stat${i}-icon-bg` });
    s.addImage({ data: img, x: x + 0.38, y: 1.98, w: 0.44, h: 0.44, objectName: `stat${i}-icon`, altText: label });
    s.addText([
      { text: big, options: { fontSize: 40, bold: true, color, breakLine: true, fontFace: "Cambria" } },
      { text: label, options: { fontSize: 17, bold: true, color: C.text1, breakLine: true } },
      { text: "ssp370, 2071–2100", options: { fontSize: 13, color: C.accent5, breakLine: true } },
      { text: sub, options: { fontSize: 13, color: C.accent5 } },
    ], { x: x + 0.25, y: 2.75, w: 2.4, h: 2.4, valign: "top", isTextBox: true, margin: 0, paraSpaceAfter: 4, objectName: `stat${i}-text` });
  });
  s.addText(`Changes for the Evanger total (${K.total_area_km2} km²) against 1991–2020, ensemble median. Snow storage shrinks: more water comes in autumn and winter, less in summer.`,
    { x: 0.6, y: 5.25, w: 12.1, h: 1.0, fontSize: 18, color: C.text1, isTextBox: true, margin: 0, objectName: "key-sentence" });
  s.addNotes("Headline: annual inflow changes by less than ±10 %, while the seasonal distribution changes strongly. Numbers are ensemble medians for the Evanger total, 2071–2100 vs 1991–2020. The ranges and the other periods are in the report.");

  // ---------- 3. case and data ----------
  pres.addSection({ title: "Data and method" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Data and method" });
  s.addText("Case and data: 21 sub-catchments, 100 model runs", { placeholder: "title" });
  const facts = [
    [ic.map, `${K.n_basins} local sub-catchments`, `Evanger system (Eviny), ${K.total_area_km2} km², 1–32 km² each (NVE outlines)`],
    [ic.grid, "KiN2025, 1 km grid", "Daily runoff (distHBV), NVE / MET Norway / NCCS"],
    [ic.models, "100 runs", `hist ${K.members.hist} · rcp26 ${K.members.rcp26} · rcp45 ${K.members.rcp45} · ssp370 ${K.members.ssp370} (10 GCM-RCMs × 2 bias adjustments)`],
    [ic.files, "6,778 files, 3.1 TB", "Every file read in full; damaged files downloaded again"],
    [ic.cal, "Periods", "Reference 1991–2020 · near 2041–2070 · far 2071–2100"],
  ];
  facts.forEach(([img, head, body], i) => {
    const y = 1.45 + i * 1.05;
    s.addShape(pres.shapes.OVAL, { x: 0.6, y, w: 0.7, h: 0.7, fill: { color: C.background2 }, line: { type: "none" }, objectName: `fact${i}-icon-bg` });
    s.addImage({ data: img, x: 0.75, y: y + 0.15, w: 0.4, h: 0.4, objectName: `fact${i}-icon`, altText: head });
    s.addText([{ text: head, options: { bold: true, fontSize: 16, color: C.text1, breakLine: true } }, { text: body, options: { fontSize: 13, color: C.accent5 } }],
      { x: 1.5, y: y - 0.05, w: 5.4, h: 0.85, valign: "middle", isTextBox: true, margin: 0, objectName: `fact${i}-text` });
  });
  // method flow
  const steps = ["Download and check KiN2025 runoff", "Basin means (1 km cells, coverage weights)", "Change of each run vs. the same run in 1991–2020", "Ensemble median and 10–90 % range"];
  steps.forEach((t, i) => {
    const y = 1.45 + i * 1.32;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 7.6, y, w: 5.1, h: 1.0, fill: { color: i === 2 ? C.accent1 : C.background2 }, line: { type: "none" }, rectRadius: 0.1, objectName: `step${i}` });
    s.addText([{ text: `${i + 1}  `, options: { bold: true, fontSize: 20, color: i === 2 ? C.background1 : C.accent1 } }, { text: t, options: { fontSize: 15, color: i === 2 ? C.background1 : C.text1 } }],
      { x: 7.85, y, w: 4.7, h: 1.0, valign: "middle", isTextBox: true, margin: 0, objectName: `step${i}-text` });
    if (i < steps.length - 1) s.addShape(pres.shapes.DOWN_ARROW, { x: 10.0, y: y + 1.03, w: 0.3, h: 0.26, fill: { color: C.accent6 }, line: { type: "none" }, objectName: `arrow${i}` });
  });
  s.addNotes("The 21 local sub-catchments come from NVE Nedbørfelt exports; the larger upstream '-nevina' variants of 03, 12 and 15 overlap the others and are left out. KiN2025 runoff is a flux (kg m-2 s-1), converted to mm/day. Step 3 is the key: each future run is compared with the same model in the reference period, which removes most of the constant model bias.");

  // ---------- 4. reference check ----------
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Data and method" });
  s.addText("KiN2025 is about 20 % below NVE: use changes, not volumes", { placeholder: "title" });
  addFigure(s, "01_reference_vs_nve.png", { x: 0.6, y: 1.35, w: 6.2, h: 5.45 }, "reference-vs-nve");
  takeaway(s, 7.3, 1.6, 5.4, 3.2, `${K.bias_ratio.median.toFixed(2)} ×`,
    `KiN2025 1991–2020 runoff relative to NVE's QN9120 normals (range ${K.bias_ratio.min.toFixed(2)}–${K.bias_ratio.max.toFixed(2)}). The bias is the same for every model and bias adjustment, so it is systematic. Apply the projected changes to observed or NVE-based inflow (delta change).`, C.accent2);
  s.addNotes("Each dot is one sub-catchment; error bars are the 10-90 % range of the 40 historical members. The spatial pattern agrees with NVE, but the level is about 20 % lower everywhere. That is why all results are relative changes.");

  // ---------- results ----------
  pres.addSection({ title: "Results" });
  figSlide("Results", "Annual inflow: small changes, large natural variability", "02_annual_timeseries_total.png",
    `${m(K.annual, "ssp370", FAR)} %`, `ssp370 by 2071–2100; rcp45 ${m(K.annual, "rcp45", FAR)} %, rcp26 ${m(K.annual, "rcp26", FAR)} %. Ten-year means vary by about ±10 % between models and decades, so the trend is small compared with variability.`,
    "Annual runoff of the Evanger total as % of each run's 1991-2020 mean, smoothed over 10 years. Lines are ensemble medians, bands the 10-90 % range. Under ssp370 the increase is about 9 %; under rcp26 there is no clear change by the end of the century.");
  figSlide("Results", "All sub-catchments change in a similar way", "03b_annual_change_map.png",
    `${sgn(K.basin_range_far.ssp370.min, 0)} to ${sgn(K.basin_range_far.ssp370.max, 0)} %`, "Range across the sub-catchments under ssp370, 2071–2100. The southern sub-catchments (04–08) gain the most.",
    "Ensemble-median change in annual runoff per sub-catchment, 2071-2100. The pattern is similar in all three scenarios; the spread between sub-catchments is small compared with the spread between scenarios.");
  figSlide("Results", "A smaller, earlier snowmelt peak and more winter inflow", "04_seasonal_cycle_total.png",
    `${m(K.seasons["JJA_%"], "ssp370", FAR)} %`, `summer (Jun–Aug) inflow under ssp370 by 2071–2100. Winter (Dec–Feb) ${m(K.seasons["DJF_%"], "ssp370", FAR)} %. The June peak shrinks and moves to May.`,
    "Monthly mean runoff for the Evanger total. Black = reference, dashed = 2041-2070, solid = 2071-2100. The snowmelt peak in June becomes smaller and earlier; autumn and winter runoff increase because more precipitation falls as rain.", C.accent2);

  // native chart: seasonal change, far future
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Results" });
  s.addText("Seasonal change grows with the emission level", { placeholder: "title" });
  const seasonsOrder = [["DJF_%", "Winter (DJF)"], ["MAM_%", "Spring (MAM)"], ["JJA_%", "Summer (JJA)"], ["SON_%", "Autumn (SON)"]];
  const chartData = ["rcp26", "rcp45", "ssp370"].map((sc) => ({ name: sc, labels: seasonsOrder.map((x) => x[1]),
    values: seasonsOrder.map(([k]) => Math.round(K.seasons[k][`${sc}|${FAR}`].median)) }));
  s.addChart(pres.charts.BAR, chartData, {
    x: 0.6, y: 1.35, w: 8.7, h: 5.45, barDir: "col", barGrouping: "clustered", barGapWidthPct: 60,
    chartColors: ["0072B2", "E69F00", "D55E00"], showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "+0;-0;0",
    dataLabelFontSize: 11, dataLabelColor: "1F2A30", dataLabelFontFace: "+mn-lt",
    showLegend: true, legendPos: "t", legendFontSize: 12, legendFontFace: "+mn-lt", legendColor: "1F2A30",
    catAxisLabelColor: "1F2A30", catAxisLabelFontSize: 13, catAxisLabelFontFace: "+mn-lt", catGridLine: { style: "none" },
    valAxisLabelColor: "5A6B75", valAxisLabelFontSize: 11, valAxisLabelFontFace: "+mn-lt", valAxisLabelFormatCode: "+0;-0;0",
    valGridLine: { color: "D9E2E7", size: 0.75 }, valAxisTitle: "Change 2071–2100 vs 1991–2020 (%)", showValAxisTitle: true,
    valAxisTitleFontSize: 12, valAxisTitleColor: "5A6B75", valAxisTitleFontFace: "+mn-lt",
    showTitle: true, title: "Evanger total, ensemble median", titleFontSize: 14, titleColor: "1F2A30", titleFontFace: "+mn-lt",
    objectName: "seasonal-change-chart",
  });
  takeaway(s, 9.6, 1.45, 3.13, 3.6, `${m(K.octmar_share_pp, "ssp370", FAR)} pp`,
    `more of the hydrological-year inflow in October–March under ssp370 (rcp26 ${m(K.octmar_share_pp, "rcp26", FAR)}, rcp45 ${m(K.octmar_share_pp, "rcp45", FAR)} percentage points). The direction is the same in all three scenarios.`);
  s.addNotes("Native chart of the seasonal change for 2071-2100. All three scenarios show the same pattern of wetter winters and springs and drier summers; the size grows from rcp26 to ssp370.");

  figSlide("Results", "Inflow arrives weeks earlier", "06_timing_winter_share_total.png",
    `${Math.abs(K.cov_shift_days["ssp370|" + FAR].median).toFixed(0)} days`, `earlier centre of volume (hydrological year) under ssp370 by 2071–2100; ${Math.abs(K.cov_shift_days["rcp26|" + FAR].median).toFixed(0)} days under rcp26. All runs agree on the direction.`,
    "Left: the day by which half of the hydrological-year (October-September) inflow has passed, shift in days. Right: change in the share of inflow in October-March. Boxes show the 20 runs per scenario.", C.accent3);
  figSlide("Results", "Summer low flows fall; 1-day peaks rise under high emissions", "08_extremes_total.png",
    `${m(K.min7d_summer, "ssp370", FAR)} %`, `summer 7-day minimum under ssp370 by 2071–2100 (rcp26 ${m(K.min7d_summer, "rcp26", FAR)} %). Annual 1-day maximum: ${m(K.max1d, "rcp26", FAR)} % (rcp26) to ${m(K.max1d, "ssp370", FAR)} % (ssp370).`,
    "Median annual 1-day and 3-day maximum runoff and the median summer 7-day minimum, as % change per run. Daily KiN2025 runoff is not routed, so 1-day peaks are approximate. No plant thresholds were available, so these are relative changes only.", C.accent2);
  figSlide("Results", "Dry years: rarer under ssp370, more frequent under rcp26", "10_dry_years_total.png",
    `${K.dry_freq_pct["ssp370|" + FAR]} %`, `of years are as dry as today's driest 20 % under ssp370 (2071–2100); ${K.dry_freq_pct["rcp26|" + FAR]} % under rcp26. Dry summers become more likely in all scenarios.`,
    "Left: share of years below each run's reference 20th percentile (20 % by definition today). Right: change in the 1-in-10 dry-year runoff. Under high emissions the annual total increases, so annual dry years become rarer; seasonal deficits are covered on the previous slide.");
  figSlide("Results", "Natural variability dominates uncertainty until 2050", "11_uncertainty_total.png",
    `~${K.uncertainty_pct["2050"].internal} %`, `of the spread in 10-year mean inflow comes from natural variability around 2050; the emission scenario reaches about ${K.uncertainty_pct["2085"].scenario} % only by 2085. Plan with the full ensemble, not one scenario.`,
    "Simplified Hawkins and Sutton split of the variance of 10-year mean annual runoff. The rcp and ssp scenarios use different model ensembles, so the split is approximate.");

  // ---------- implications ----------
  pres.addSection({ title: "Discussion" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Discussion" });
  s.addText("What it may mean for hydropower operation", { placeholder: "title" });
  const impl = [
    [ic.winter, C.accent4, "More winter inflow", "More water when demand and prices are usually high; less need to store water for winter, but more spill risk with full reservoirs."],
    [ic.sun, C.accent2, "Smaller, earlier snowmelt", "Summer reservoir filling may become harder; filling strategies and water values may need to change (RP2.4, RP3.3)."],
    [ic.drop, C.accent3, "Lower summer low flows", "Minimum-flow requirements may be harder to meet; relevant for dynamic ecological flows (RP3.5)."],
    [ic.flood, C.accent1, "Changing flood season", "Under high emissions, more autumn and winter rain floods and fewer snowmelt floods (RP3.2, RP3.4)."],
    [ic.bolt, C.accent5, "Annual energy", "A small increase under rcp45 and ssp370; the change in timing probably matters more than the volume."],
  ];
  impl.forEach(([img, color, head, body], i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 0.6 + col * 6.15, y = 1.45 + row * 1.75;
    s.addShape(pres.shapes.OVAL, { x, y, w: 0.75, h: 0.75, fill: { color }, line: { type: "none" }, objectName: `impl${i}-icon-bg` });
    s.addImage({ data: img, x: x + 0.16, y: y + 0.16, w: 0.43, h: 0.43, objectName: `impl${i}-icon`, altText: head });
    s.addText([{ text: head, options: { bold: true, fontSize: 17, color: C.text1, breakLine: true } }, { text: body, options: { fontSize: 14, color: C.text1 } }],
      { x: x + 0.95, y: y - 0.05, w: 4.9, h: 1.5, valign: "top", isTextBox: true, margin: 0, paraSpaceAfter: 4, objectName: `impl${i}-text` });
  });
  s.addText("Indicative only: natural inflow without regulation. To be tested with Eviny's plant data and operation models.",
    { x: 6.75, y: 5.0, w: 5.95, h: 1.2, fontSize: 14, italic: true, color: C.accent5, isTextBox: true, margin: 0, valign: "middle", objectName: "impl-caveat" });
  s.addNotes("These points connect the inflow changes to operation. They are hypotheses for discussion with Eviny, not results of an operation model.");

  // ---------- limitations ----------
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Discussion" });
  s.addText("Limitations to keep in mind", { placeholder: "title" });
  const lim = [
    ["Natural, local runoff", "No regulation, transfers, reservoirs or river routing in KiN2025 runoff."],
    ["Bias against NVE", `Reference runoff about ${Math.round((1 - K.bias_ratio.median) * 100)} % below NVE normals: use relative changes.`],
    ["Small basins", "Several sub-catchments cover only one or two 1 km grid cells."],
    ["Two different ensembles", "rcp26/rcp45 use CMIP5 models, ssp370 uses CMIP6; 20 runs per scenario are not independent."],
    ["No plant data", "Spill, production and minimum-flow compliance need Eviny's plant-specific numbers."],
    ["Approximate peaks", "Daily, unrouted runoff: 1-day peaks are indicative, not design floods."],
  ];
  lim.forEach(([head, body], i) => {
    const col = i % 3, row = Math.floor(i / 3);
    const x = 0.6 + col * 4.1, y = 1.7 + row * 2.4;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: 3.85, h: 2.0, fill: { color: C.background2 }, line: { type: "none" }, rectRadius: 0.12, objectName: `lim${i}-card` });
    s.addText([{ text: head, options: { bold: true, fontSize: 18, color: C.accent1, breakLine: true } }, { text: body, options: { fontSize: 15, color: C.text1 } }],
      { x: x + 0.25, y: y + 0.2, w: 3.35, h: 1.6, valign: "top", isTextBox: true, margin: 0, paraSpaceAfter: 6, objectName: `lim${i}-text` });
  });
  s.addNotes("Main caveats. The most important for users: these are natural inflows, and absolute volumes are biased low, so use relative changes.");

  // ---------- data availability ----------
  pres.addSection({ title: "Data and next steps" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Data and next steps" });
  s.addText("D3.1.3: the projected runoff is available on NIRD", { placeholder: "title" });
  s.addText("/nird/datapeak/NS10014K/WP6/luli/RenewHydro_data/D3.1.3_KiN2025_Evanger_runoff", { x: 0.6, y: 1.4, w: 12.1, h: 0.5, fontSize: 15, fontFace: "Courier New", color: C.accent1, isTextBox: true, margin: 0, objectName: "nird-path" });
  const hdr = (t) => ({ text: t, options: { bold: true, color: HEX.lt1, fill: { color: HEX.dk1 }, fontSize: 14 } });
  const row = (a, b, c) => [{ text: a, options: { fontSize: 14, bold: true } }, { text: b, options: { fontSize: 14 } }, { text: c, options: { fontSize: 14 } }];
  s.addTable([
    [hdr("Folder / file"), hdr("Content"), hdr("Format")],
    row("daily_csv/", `One file per sub-catchment (${K.n_basins} + total): daily runoff in mm/day and m³/s, all scenarios and runs`, "CSV (gzip)"),
    row("netcdf/", "One file per scenario: runoff(basin, member, time)", "NetCDF-4"),
    row("basins/", "Outlines and attributes, incl. NVE normals", "GeoPackage, GeoJSON"),
    row("members.csv", "All 100 runs with model, bias adjustment and years", "CSV"),
    row("README.md", "Units, method, caveats, how to cite KiN2025", "Markdown"),
  ], { x: 0.6, y: 2.1, w: 12.1, colW: [2.4, 7.6, 2.1], color: HEX.dk1, border: { type: "solid", pt: 0.75, color: "C9D6DC" }, rowH: 0.55, valign: "middle", objectName: "data-table" });
  s.addText("Access: members of NIRD project NS10014K. Code: GitHub luli420/RenewHydro.", { x: 0.6, y: 6.1, w: 12.1, h: 0.5, fontSize: 14, color: C.accent5, isTextBox: true, margin: 0, objectName: "access-note" });
  s.addNotes("The deliverable D3.1.3: everything needed to use the projections, with documentation. Ask Lu Li for access if you are not in NS10014K.");

  // ---------- questions & next steps (closing) ----------
  s = pres.addSlide({ masterName: "CLOSING_DARK", sectionTitle: "Data and next steps" });
  s.addText("Questions for Eviny", { placeholder: "title" });
  const asks = [
    ["Which sub-catchments feed which reservoir and plant?", "inflow per plant"],
    ["Energy equivalents (kWh/m³) per intake?", "inflow in GWh"],
    ["Reservoir volumes, Qmax, minimum-flow rules?", "spill, production loss, minimum-flow compliance"],
    ["Observed or naturalised inflow series?", "bias check, climate-adjusted series"],
    ["Inflow format of your planning models?", "scenarios ready for water-value models"],
  ];
  asks.forEach(([q, gives], i) => {
    const y = 1.6 + i * 0.82;
    s.addShape(pres.shapes.OVAL, { x: 0.8, y: y + 0.08, w: 0.5, h: 0.5, fill: { color: C.accent1 }, line: { type: "none" }, objectName: `ask${i}-dot` });
    s.addText(String(i + 1), { x: 0.8, y: y + 0.08, w: 0.5, h: 0.5, fontSize: 16, bold: true, color: C.background1, align: "center", valign: "middle", isTextBox: true, margin: 0, objectName: `ask${i}-num` });
    s.addText([{ text: q, options: { fontSize: 18, color: C.background1, bold: true } }, { text: "  →  " + gives, options: { fontSize: 16, color: C.accent6 } }],
      { x: 1.5, y, w: 11.0, h: 0.66, valign: "middle", isTextBox: true, margin: 0, objectName: `ask${i}-text` });
  });
  s.addText("Next: near-term inflow (2025–2035) with Climate Futures (NORCE) · flood statistics with routing · inflow in GWh",
    { x: 0.8, y: 6.0, w: 11.7, h: 0.6, fontSize: 16, color: C.background2, isTextBox: true, margin: 0, objectName: "next-steps" });
  s.addNotes("Close with the questions to Eviny: with plant data we can turn natural inflow into plant-relevant results. Next scientific steps are near-term predictions, routed floods and energy conversion.");

  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", OUT);
})();
