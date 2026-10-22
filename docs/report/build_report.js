// Build the Evanger KiN2025 inflow report (Word) from the notebook outputs.
// Usage: node build_report.js <figures_dir> <out.docx> <package_info.json>
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, ImageRun, Table, TableRow, TableCell, WidthType, ShadingType,
  HeadingLevel, AlignmentType, LevelFormat, Footer, PageNumber, BorderStyle, PageBreak, TableOfContents,
} = require("docx");

const FIG = process.argv[2];
const OUT = process.argv[3];
const PKG = process.argv[4] ? JSON.parse(fs.readFileSync(process.argv[4], "utf8")) : {};
const K = JSON.parse(fs.readFileSync(path.join(FIG, "key_numbers.json"), "utf8"));
const BT = JSON.parse(fs.readFileSync(path.join(FIG, "basin_table.json"), "utf8"));

const NAVY = "0E2A3B", TEAL = "1B6F8A", GREY = "5A6B75", LIGHT = "E8F0F3";
const SC = ["rcp26", "rcp45", "ssp370"], NEAR = "Near 2041–2070", FAR = "Far 2071–2100";
const CONTENT_W = 9070; // A4 minus 2.5 cm margins, DXA

// ---------- number helpers ----------
const sgn = (v, d = 1) => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(d);
const get = (block, s, p) => block[`${s}|${p}`];
const med = (block, s, p, d = 1) => sgn(get(block, s, p).median, d);
const rng = (block, s, p, d = 1) => `${sgn(get(block, s, p).p10, d)} to ${sgn(get(block, s, p).p90, d)}`;
const allMed = (block) => Object.values(block).map((x) => x.median);
const minMax = (block) => [Math.min(...allMed(block)), Math.max(...allMed(block))];
const pct = (v) => `${sgn(v)} %`;

// ---------- paragraph helpers ----------
const P = (text, opts = {}) => new Paragraph({ spacing: { after: 120, line: 276 }, ...opts,
  children: (Array.isArray(text) ? text : [text]).map((t) => (typeof t === "string" ? new TextRun(t) : t)) });
const B = (t) => new TextRun({ text: t, bold: true });
const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(t)] });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] });
const bullet = (parts) => new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80, line: 264 },
  children: (Array.isArray(parts) ? parts : [parts]).map((t) => (typeof t === "string" ? new TextRun(t) : t)) });

let figNo = 0;
function figure(file, caption, widthPx = 600) {
  const buf = fs.readFileSync(path.join(FIG, file));
  const w = buf.readUInt32BE(16), h = buf.readUInt32BE(20);
  figNo += 1;
  return [
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 120, after: 60 }, keepNext: true,
      children: [new ImageRun({ type: "png", data: buf, transformation: { width: widthPx, height: Math.round(widthPx * h / w) },
        altText: { title: `Figure ${figNo}`, description: caption, name: file } })] }),
    new Paragraph({ spacing: { after: 200 }, children: [
      new TextRun({ text: `Figure ${figNo}. `, bold: true, size: 19, color: GREY }),
      new TextRun({ text: caption, size: 19, color: GREY })] }),
  ];
}

const border = { style: BorderStyle.SINGLE, size: 4, color: "B8C7CF" };
const borders = { top: border, bottom: border, left: border, right: border };
function table(headers, rows, widths, opts = {}) {
  const cell = (text, w, head, shade) => new TableCell({
    width: { size: w, type: WidthType.DXA }, borders,
    shading: head ? { fill: NAVY, type: ShadingType.CLEAR, color: "auto" } : shade ? { fill: LIGHT, type: ShadingType.CLEAR, color: "auto" } : undefined,
    margins: { top: 60, bottom: 60, left: 90, right: 90 },
    children: [new Paragraph({ alignment: opts.alignNum && !head ? AlignmentType.LEFT : AlignmentType.LEFT,
      children: [new TextRun({ text: String(text), bold: head, color: head ? "FFFFFF" : "1F2A30", size: opts.size || 19 })] })],
  });
  return new Table({
    width: { size: widths.reduce((a, b) => a + b, 0), type: WidthType.DXA }, columnWidths: widths,
    rows: [new TableRow({ tableHeader: true, children: headers.map((h, i) => cell(h, widths[i], true)) }),
      ...rows.map((r, j) => new TableRow({ children: r.map((c, i) => cell(c, widths[i], false, opts.shadeLast && j === rows.length - 1)) }))],
  });
}

// ---------- derived numbers ----------
const seasons = K.seasons;
const [djfMin, djfMax] = minMax(seasons["DJF_%"]);
const [mamMin, mamMax] = minMax(seasons["MAM_%"]);
const [jjaMin, jjaMax] = minMax(seasons["JJA_%"]);
const [sonMin, sonMax] = minMax(seasons["SON_%"]);
const [covMin, covMax] = minMax(K.cov_shift_days);
const [winMin, winMax] = minMax(K.octmar_share_pp);
const [lowMin, lowMax] = minMax(K.min7d_summer);
const unc = K.uncertainty_pct;
const br = K.basin_range_far;

// ---------- content ----------
const children = [];

// Title page
children.push(
  new Paragraph({ spacing: { before: 2400, after: 200 }, children: [new TextRun({ text: "Climate change and inflow to the Evanger hydropower system", bold: true, size: 48, color: NAVY, font: "Cambria" })] }),
  new Paragraph({ spacing: { after: 600 }, children: [new TextRun({ text: `Projected runoff (KiN2025) for ${K.n_basins} sub-catchments, 1971–2100`, size: 30, color: TEAL })] }),
  P([B("Project: "), "RenewHydro — Norwegian research centre for renewal of hydropower technology (FME)"]),
  P([B("Tasks: "), "A3.1.3 Projected runoff for the case-study catchments · A3.1.5 Changes in inflow magnitude and seasonality"]),
  P([B("Deliverable: "), "D3.1.3 Projected runoff (KiN2025) for the Evanger sub-basins made available to the project"]),
  P([B("Case study: "), "Evanger hydropower system (Eviny), Vestland"]),
  P([B("Author: "), "Lu Li, NORCE Norwegian Research Centre"]),
  P([B("Version: "), "Draft for discussion, October 2026"]),
  new Paragraph({ children: [new PageBreak()] }),
);

children.push(new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-2" }), new Paragraph({ children: [new PageBreak()] }));

// 1 Summary
children.push(H1("1. Summary"));
children.push(P(`We extracted daily runoff from the Klima i Norge 2025 (KiN2025) hydrological projections for the ${K.n_basins} local sub-catchments of the Evanger hydropower system (${K.total_area_km2} km² in total), for 40 historical and 60 future model runs, and analysed the projected changes in inflow magnitude and seasonality. All changes compare each future run with the same model in 1991–2020. Ranges are the 10–90 % spread across the ensemble.`));
children.push(P(B("Key findings")));
children.push(
  bullet([B("Annual inflow changes little. "), `Under low emissions (rcp26) the change is ${med(K.annual, "rcp26", NEAR)} % in 2041–2070 and ${med(K.annual, "rcp26", FAR)} % in 2071–2100; under rcp45 ${med(K.annual, "rcp45", NEAR)} % and ${med(K.annual, "rcp45", FAR)} %; under ssp370 ${med(K.annual, "ssp370", NEAR)} % and ${med(K.annual, "ssp370", FAR)} % (range ${rng(K.annual, "ssp370", FAR)} %).`]),
  bullet([B("The seasons change strongly. "), `Winter (Dec–Feb) inflow rises by ${sgn(djfMin, 0)} to ${sgn(djfMax, 0)} %, spring (Mar–May) by ${sgn(mamMin, 0)} to ${sgn(mamMax, 0)} % and autumn (Sep–Nov) by ${sgn(sonMin, 0)} to ${sgn(sonMax, 0)} %, while summer (Jun–Aug) inflow falls by ${Math.abs(jjaMax).toFixed(0)} to ${Math.abs(jjaMin).toFixed(0)} %. Less snow is stored in winter, and the snowmelt flood becomes smaller and earlier.`]),
  bullet([B("Inflow comes earlier. "), `Half of the hydrological-year inflow has passed ${Math.abs(covMax).toFixed(0)} to ${Math.abs(covMin).toFixed(0)} days earlier than today. The share of inflow in October–March rises by ${winMin.toFixed(0)} to ${winMax.toFixed(0)} percentage points.`]),
  bullet([B("Summer low flows decrease. "), `The summer 7-day minimum runoff falls by ${Math.abs(lowMax).toFixed(0)} to ${Math.abs(lowMin).toFixed(0)} %. Annual 1-day maximum runoff hardly changes under rcp26 and rcp45 and rises by about ${med(K.max1d, "ssp370", NEAR, 0)} to ${med(K.max1d, "ssp370", FAR, 0)} % under ssp370.`]),
  bullet([B("Dry years: "), `years as dry as today's driest 20 % occur in ${K.dry_freq_pct["ssp370|" + FAR]} % of years under ssp370 (2071–2100), but in ${K.dry_freq_pct["rcp26|" + FAR]} % of years under rcp26.`]),
  bullet([B("The sub-catchments change in a similar way. "), `Under ssp370 (2071–2100) the annual change ranges from ${sgn(br.ssp370.min)} % to ${sgn(br.ssp370.max)} %; it is largest in the southern sub-catchments (04–08).`]),
  bullet([B("Natural variability dominates the uncertainty until mid-century. "), `For 10-year mean inflow, internal variability explains about ${unc["2030"].internal}–${unc["2050"].internal} % and model differences ${unc["2050"]["model × bias adj."]}–${unc["2030"]["model × bias adj."]} % of the spread up to 2050; the emission scenario reaches about ${unc["2085"].scenario} % only by 2085.`]),
  bullet([B("Use relative changes. "), `KiN2025 reference runoff is about ${K.bias_ratio.median.toFixed(2)} × NVE's 1991–2020 normals here (range ${K.bias_ratio.min.toFixed(2)}–${K.bias_ratio.max.toFixed(2)}). The changes above should be applied to observed or NVE-based inflow (delta change).`]),
  bullet([B("Data: "), "the full daily data set (D3.1.3) is on NIRD, with documentation (Section 7)."]),
);

children.push(P(B("Headline numbers (Evanger total, ensemble median)")));
const headRows = [
  ["Annual inflow", "annual"], ["Winter Dec–Feb", "DJF"], ["Summer Jun–Aug", "JJA"], ["Summer 7-day low flow", "min7d"], ["Annual 1-day maximum", "max1d"],
].map(([label, key]) => {
  const blk = key === "annual" ? K.annual : key === "min7d" ? K.min7d_summer : key === "max1d" ? K.max1d : seasons[`${key}_%`];
  return [label, ...SC.flatMap((s) => [med(blk, s, NEAR, 0) + " %", med(blk, s, FAR, 0) + " %"])];
});
headRows.push(["Timing (centre of volume)", ...SC.flatMap((s) => [med(K.cov_shift_days, s, NEAR, 0) + " d", med(K.cov_shift_days, s, FAR, 0) + " d"])]);
children.push(table(["", "rcp26 2041–70", "rcp26 2071–2100", "rcp45 2041–70", "rcp45 2071–2100", "ssp370 2041–70", "ssp370 2071–2100"],
  headRows, [2290, 1130, 1130, 1130, 1130, 1130, 1130], { size: 18 }));
children.push(P(""));

// 2 Background
children.push(H1("2. Background and purpose"));
children.push(P("RenewHydro develops knowledge and solutions for flexible hydropower under the energy transition and a changing climate. Shared user cases link the research to the user partners. This report covers the climate-change inflow analysis for the Evanger case (Eviny) and documents three Work Package 3 tasks:"));
children.push(
  bullet([B("A3.1.3 — "), "provide projected runoff for the case-study catchments (Evanger sub-basins) based on KiN2025 (NVE/MET Norway, 1 km);"]),
  bullet([B("A3.1.5 — "), "analyse projected changes in inflow magnitude and seasonality for these catchments;"]),
  bullet([B("D3.1.3 — "), "make the projected runoff available to the project."]),
);
children.push(P("The work also contributes to Framework Program FP5 (trends in runoff and effects on hydropower production) and to RP3 (climate adaptation: changed seasonality, extremes and ecological flows), and it provides inflow scenarios for water-value and security-of-supply studies (RP2.3, RP2.4)."));

// 3 Data and methods
children.push(H1("3. Data and methods"));
children.push(H2("3.1 KiN2025 hydrological projections"));
children.push(P("KiN2025 (Klima i Norge 2025, Norwegian Centre for Climate Services) provides daily runoff (mrro) from the distributed HBV model (distHBV-COR-BA-2025) on a 1 km grid for all of Norway. The model is driven by bias-adjusted EURO-CORDEX regional climate simulations. We downloaded all 6,778 daily files (3.1 TB) and read every file in full to check it; damaged files were downloaded again."));
children.push(table(["Scenario", "Years", "Driving models", "Members"], [
  ["hist", "1971–2020", "10 CMIP5 + 10 CMIP6 GCM-RCMs", `${K.members.hist}`],
  ["rcp26", "2021–2100", "10 CMIP5 GCM-RCMs", `${K.members.rcp26}`],
  ["rcp45", "2021–2100", "10 CMIP5 GCM-RCMs", `${K.members.rcp45}`],
  ["ssp370", "2021–2100*", "10 CMIP6 GCM-RCMs", `${K.members.ssp370}`],
], [1700, 1600, 4170, 1600]));
children.push(new Paragraph({ spacing: { before: 120, after: 200 }, children: [new TextRun({ text: "Each GCM-RCM is run with two bias adjustments (EQM and 3DBC-EQM), giving 20 members per scenario. *Two HadGEM runs (rcp26/rcp45) end in 2098 and three CMIP6 runs (ssp370) end in 2099.", size: 18, color: GREY })] }));

children.push(H2("3.2 Evanger sub-catchments and basin runoff"));
children.push(P(`The case uses the ${K.n_basins} local sub-catchments of the Evanger system delineated by NVE (Nedbørfelt exports, ${K.total_area_km2} km² in total; 1.0 to 32 km² each). For three intakes (03, 12, 15) NVE also delivered larger upstream variants ("-nevina"); these overlap other sub-catchments and were left out. Daily basin runoff is the coverage-weighted mean of the 1 km cells inside each basin. KiN2025 stores runoff as a flux (kg m⁻² s⁻¹), which we converted to mm/day. The series EVANGER_TOTAL is the area-weighted mean of all ${K.n_basins} sub-catchments.`));

children.push(H2("3.3 Analysis approach"));
children.push(
  bullet([B("Periods: "), "reference 1991–2020 (hist), near future 2041–2070 and far future 2071–2100."]),
  bullet([B("Member-wise change: "), "each future member is compared with the same model and bias adjustment in the reference period, and the ensemble is then summarised as the median and the 10–90 % range. This removes most of the constant model bias."]),
  bullet([B("Seasonality: "), "monthly and seasonal means; the centre-of-volume date and the October–March share, both on the hydrological year (October–September)."]),
  bullet([B("Extremes without plant data: "), "the median annual maximum of 1-day and 3-day runoff, and the median summer (June–September) 7-day minimum, as relative changes. No minimum-flow, reservoir or turbine data were available."]),
  bullet([B("Dry years: "), "the share of years below each member's reference 20th percentile, and the change in the 1-in-10 dry-year runoff."]),
  bullet([B("Uncertainty: "), "a simplified Hawkins and Sutton (2009) split of the variance of 10-year mean runoff into scenario, model (GCM-RCM × bias adjustment) and internal variability."]),
);

children.push(H2("3.4 Reference check against NVE"));
children.push(P(`KiN2025 reproduces the spatial pattern of NVE's 1991–2020 runoff normals (QN9120) but is lower in all sub-catchments: the median ratio is ${K.bias_ratio.median.toFixed(2)} (range ${K.bias_ratio.min.toFixed(2)}–${K.bias_ratio.max.toFixed(2)}), and the result is the same for every model and both bias adjustments. The bias is therefore systematic, and absolute KiN2025 volumes should not be used directly for planning. Relative changes are much less affected.`));
children.push(...figure("01_reference_vs_nve.png", "KiN2025 hist 1991–2020 mean annual runoff (ensemble median, 10–90 % range) against NVE's QN9120 normals for the 21 sub-catchments.", 380));

// 4 Results
children.push(H1("4. Results"));
children.push(H2("4.1 Annual inflow"));
children.push(P(`The annual inflow to the Evanger system (reference ${K.ref_mm_total.toFixed(0)} mm/yr in KiN2025) changes by ${med(K.annual, "rcp26", FAR)} % (rcp26), ${med(K.annual, "rcp45", FAR)} % (rcp45) and ${med(K.annual, "ssp370", FAR)} % (ssp370) by 2071–2100. Year-to-year and model differences are large compared with these changes (Figure 2): even the 10-year mean varies by about ±10 % around the trend.`));
children.push(...figure("02_annual_timeseries_total.png", "Annual runoff of EVANGER_TOTAL as % of each member's 1991–2020 mean, 10-year running mean; line = ensemble median, band = 10–90 %."));
children.push(P(`The change is similar across the sub-catchments (Figure 3). Under ssp370 (2071–2100) it ranges from ${sgn(br.ssp370.min)} % to ${sgn(br.ssp370.max)} %, under rcp45 from ${sgn(br.rcp45.min)} % to ${sgn(br.rcp45.max)} %, and under rcp26 from ${sgn(br.rcp26.min)} % to ${sgn(br.rcp26.max)} %. The southern sub-catchments (04–08) gain the most. Appendix A lists all values.`));
children.push(...figure("03b_annual_change_map.png", "Change in mean annual runoff, 2071–2100 vs 1991–2020, ensemble median per sub-catchment."));

children.push(H2("4.2 Seasonal cycle"));
children.push(P(`Today the inflow is dominated by snowmelt in May–July, with a peak in June, and a second, rain-driven maximum in October (Figure 4). In all scenarios the snowmelt peak becomes smaller and earlier, and winter inflow rises. The changes grow with the emission level: by 2071–2100 under ssp370, December–February inflow is ${med(seasons["DJF_%"], "ssp370", FAR, 0)} % and June–August inflow ${med(seasons["JJA_%"], "ssp370", FAR, 0)} % (Figure 5). July shows the largest decrease (${sgn(K.monthly_median["ssp370|" + FAR][6], 0)} %).`));
children.push(...figure("04_seasonal_cycle_total.png", "Monthly mean runoff of EVANGER_TOTAL: reference 1991–2020 (black) and 2041–2070 (dashed) / 2071–2100 (solid); ensemble median and 10–90 % band."));
children.push(...figure("05_monthly_change_total.png", "Change in monthly runoff of EVANGER_TOTAL (ensemble median, %)."));

children.push(H2("4.3 Timing and winter share"));
children.push(P(`On the hydrological year, the date by which half of the year's inflow has passed moves ${Math.abs(K.cov_shift_days["rcp26|" + FAR].median).toFixed(0)} days earlier under rcp26 and ${Math.abs(K.cov_shift_days["ssp370|" + FAR].median).toFixed(0)} days earlier under ssp370 by 2071–2100. The October–March share of the inflow rises by ${med(K.octmar_share_pp, "rcp26", FAR)} to ${med(K.octmar_share_pp, "ssp370", FAR)} percentage points (Figure 6). All members agree on the direction.`));
children.push(...figure("06_timing_winter_share_total.png", "EVANGER_TOTAL: shift of the centre-of-volume date (days) and change in the October–March share of hydrological-year inflow (percentage points); boxes = ensemble members."));

children.push(H2("4.4 High and low flows"));
children.push(P(`The median annual 1-day maximum changes by ${med(K.max1d, "rcp26", FAR)} % (rcp26), ${med(K.max1d, "rcp45", FAR)} % (rcp45) and ${med(K.max1d, "ssp370", FAR)} % (ssp370) by 2071–2100, and the 3-day maximum by ${med(K.max3d, "rcp26", FAR)}, ${med(K.max3d, "rcp45", FAR)} and ${med(K.max3d, "ssp370", FAR)} % (Figure 7). This is consistent with smaller snowmelt peaks and more autumn and winter rain floods (Section 4.2), so the season of the largest flows may shift. Summer low flows decrease clearly: the 7-day minimum in June–September changes by ${med(K.min7d_summer, "rcp26", FAR)} % (rcp26), ${med(K.min7d_summer, "rcp45", FAR)} % (rcp45) and ${med(K.min7d_summer, "ssp370", FAR)} % (ssp370). Note that daily KiN2025 runoff is not routed, so 1-day peaks are approximate.`));
children.push(...figure("08_extremes_total.png", "EVANGER_TOTAL: change in the median annual 1-day and 3-day maximum runoff and in the median summer 7-day minimum runoff (%)."));

children.push(H2("4.5 Dry years"));
children.push(P(`A year is counted as dry when its runoff is below the member's own reference 20th percentile (20 % of reference years). Under ssp370 such years become rarer (${K.dry_freq_pct["ssp370|" + NEAR]} % of years in both periods), because the annual total increases. Under rcp26 they become slightly more common by 2071–2100 (${K.dry_freq_pct["rcp26|" + FAR]} %). The 1-in-10 dry-year runoff changes by ${med(K.p10_dry_year, "rcp26", FAR)} % (rcp26) to ${med(K.p10_dry_year, "ssp370", FAR)} % (ssp370) by 2071–2100 (Figure 8). Seasonal deficits matter more for operation than annual ones: dry summers become more likely in all scenarios (Section 4.4).`));
children.push(...figure("10_dry_years_total.png", "EVANGER_TOTAL: frequency of reference-dry years (reference = 20 %) and change in the 1-in-10 dry-year runoff."));

children.push(H2("4.6 Sources of uncertainty"));
children.push(P(`For 10-year mean annual inflow, internal (natural) variability is the largest source of uncertainty until mid-century (about ${unc["2030"].internal} % in 2030 and ${unc["2050"].internal} % in 2050), followed by model differences (about ${unc["2050"]["model × bias adj."]}–${unc["2030"]["model × bias adj."]} %). The emission scenario matters more later (about ${unc["2070"].scenario} % in 2070 and ${unc["2085"].scenario} % in 2085; Figure 9). For planning horizons up to about 2050, a robust approach therefore uses the full ensemble and accounts for natural variability, rather than choosing one scenario. Note that rcp and ssp scenarios use different model ensembles, so the split is approximate.`));
children.push(...figure("11_uncertainty_total.png", "EVANGER_TOTAL: share of the variance of 10-year mean annual runoff from scenario, model (GCM-RCM × bias adjustment) and internal variability."));

// 5 Implications
children.push(H1("5. What the results may mean for hydropower operation"));
children.push(P("These points are indicative. They are based on natural inflow without regulation, and should be discussed with Eviny and tested with plant data and operation models:"));
children.push(
  bullet([B("More winter inflow. "), "More water arrives when demand and prices are usually highest. This can reduce the need to store water from summer to winter, but can also increase spill risk when reservoirs are full in autumn and winter."]),
  bullet([B("Smaller and earlier snowmelt flood. "), "Reservoir filling over the summer may become harder, and filling and release strategies and water values may need to change (RP2.4, RP3.3)."]),
  bullet([B("Lower summer low flows. "), "Meeting minimum-flow requirements (minstevannføring) may become more demanding, which is relevant for dynamic ecological flows (RP3.5)."]),
  bullet([B("Changing flood season. "), "Under high emissions, rain floods in autumn and winter increase while snowmelt floods decrease. This matters for spill and flood handling (RP3.2, RP3.4)."]),
  bullet([B("Annual energy. "), "Annual inflow increases slightly under rcp45 and ssp370. The change in timing is larger and probably more important for operation than the change in annual volume."]),
);

// 6 Limitations
children.push(H1("6. Limitations"));
children.push(
  bullet([B("Natural, local runoff. "), "KiN2025 mrro has no regulation, transfers, reservoirs or river routing."]),
  bullet([B("Bias against NVE normals. "), `KiN2025 runoff is about ${Math.round((1 - K.bias_ratio.median) * 100)} % lower than NVE's normals for these basins. Use relative changes.`]),
  bullet([B("Small basins. "), "Several sub-catchments cover only one or two 1 km grid cells."]),
  bullet([B("Ensembles. "), "rcp26/rcp45 (CMIP5) and ssp370 (CMIP6) use different models; the 20 members per scenario are 10 models × 2 bias adjustments and are not independent."]),
  bullet([B("No plant data. "), "Extremes are shown as relative changes; spill, production and minimum-flow compliance need plant-specific data."]),
);

// 7 Data availability
children.push(H1("7. Data availability (D3.1.3)"));
children.push(P([`The projected daily runoff is available to the project on NIRD Data Peak:`]));
children.push(P([new TextRun({ text: PKG.nird_path || "/nird/datapeak/NS10014K/WP6/luli/RenewHydro_data/D3.1.3_KiN2025_Evanger_runoff", font: "Courier New", size: 18 })]));
children.push(table(["Item", "Content", "Format"], [
  ["daily_csv/", `One file per basin (${K.n_basins} + EVANGER_TOTAL), all scenarios and members: runoff in mm/day and discharge in m³/s`, "CSV (gzip)"],
  ["netcdf/", "One file per scenario: runoff(basin, member, time) in mm/day with basin areas", "NetCDF-4"],
  ["basins/", "Sub-catchment outlines (UTM 33N and WGS84) and attributes, including NVE normals", "GeoPackage, GeoJSON, CSV"],
  ["members.csv", "All scenario × model × bias-adjustment members with years", "CSV"],
  ["README.md, checksums.md5", "Documentation and file checksums", "Markdown, text"],
], [2100, 5170, 1800]));
children.push(P(""));
children.push(P(`${PKG.size ? `Total size: ${PKG.size}. ` : ""}Access requires membership of the NIRD project NS10014K. The code that produced the data and this analysis is on GitHub (luli420/RenewHydro). KiN2025 should be cited when the data are used, and its licence terms checked before the data are shared outside the project.`));

// 8 Next steps
children.push(H1("8. Next steps and questions for Eviny"));
children.push(table(["Ask Eviny for", "Makes possible"], [
  ["Which sub-catchments drain to which reservoir, intake and plant", "Inflow per plant and reservoir instead of per sub-catchment"],
  ["Energy equivalents (kWh/m³) per intake", "Inflow and its changes in GWh"],
  ["Reservoir volumes, maximum turbine flow and minimum-flow rules", "Spill, production loss and minimum-flow compliance under future inflow"],
  ["Observed or naturalised inflow series", "Check of the KiN2025 bias and climate-adjusted inflow series"],
  ["The inflow format used in Eviny's planning models", "Scenarios that can be used directly in water-value and production models"],
], [4300, 4770]));
children.push(P(""));
children.push(P("Planned scientific next steps: near-term (2025–2035) inflow from decadal and seasonal predictions together with Climate Futures (NORCE); flood statistics with routing; and conversion to energy once energy equivalents are available."));

// Appendix
children.push(new Paragraph({ children: [new PageBreak()] }), H1("Appendix A. Change in mean annual runoff per sub-catchment"));
children.push(P("Ensemble median change (%) against 1991–2020; N = 2041–2070, F = 2071–2100."));
children.push(table(["Sub-catchment", "km²", "rcp26 N", "rcp26 F", "rcp45 N", "rcp45 F", "ssp370 N", "ssp370 F"],
  BT.map((r) => [r.basin, r.area.toFixed(1), ...SC.flatMap((s) => [sgn(r[`${s}|Near`]), sgn(r[`${s}|Far`])])]),
  [2470, 700, 980, 980, 980, 980, 990, 990], { size: 17, shadeLast: true }));
children.push(P(""));
children.push(H1("Appendix B. Further figures"));
children.push(...figure("03_annual_change_heatmap.png", "Change in mean annual runoff for every sub-catchment, scenario and period (ensemble median, %).", 520));
children.push(...figure("07_timing_winter_share_basins.png", "Centre-of-volume shift (days) and change in October–March share (percentage points) for every sub-catchment."));
children.push(...figure("09_extremes_basins.png", "Change in the median annual 1-day maximum and the summer 7-day minimum runoff for every sub-catchment (%)."));

// ---------- document ----------
const doc = new Document({
  creator: "Lu Li (NORCE)", title: "Climate change and inflow to the Evanger hydropower system",
  description: "RenewHydro A3.1.3, A3.1.5, D3.1.3",
  styles: {
    default: { document: { run: { font: "Calibri", size: 22, color: "1F2A30" } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, color: NAVY, font: "Cambria" }, paragraph: { spacing: { before: 360, after: 160 }, outlineLevel: 0, keepNext: true } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, color: TEAL, font: "Cambria" }, paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1, keepNext: true } },
    ],
  },
  numbering: { config: [{ reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
    style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] }] },
  features: { updateFields: true },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1418, bottom: 1418, left: 1418, right: 1418 } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [
      new TextRun({ text: "RenewHydro · Evanger inflow projections (KiN2025) · ", size: 16, color: GREY }),
      new TextRun({ children: [PageNumber.CURRENT], size: 16, color: GREY })] })] }) },
    children,
  }],
});
Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(OUT, buf); console.log("wrote", OUT, figNo, "figures"); });
