"""
Shared configuration for the KiN2025 mrro pipeline: OPeNDAP location, the
20-member ensemble definition (10 GCM-RCM pairs x 2 bias-adjustment methods),
and scenario/year coverage.

Values here are confirmed against the live THREDDS catalog (used
successfully by download_mrro_KlimaiNorge.sh and
download_mrro_VN_sKlimaiNorge2025.py) -- unlike the OPeNDAP paths in the
older extract_evanger_runoff.py (NEVINA-based, superseded), which were
unverified guesses. See CLAUDE.md.
"""

from __future__ import annotations

from dataclasses import dataclass

OPENDAP_BASE = "https://thredds.met.no/thredds/dodsC/KSS/Klima_i_Norge/utgave2025/DailyTimeSeries/mrro"
FILESERVER_BASE = "https://thredds.met.no/thredds/fileServer/KSS/Klima_i_Norge/utgave2025/DailyTimeSeries/mrro"

VARIABLE = "mrro"

# seNorge grid: the archive is indexed by Xc/Yc, not x/y or lon/lat -- see
# find_grid_index_bbox.py to turn a lon/lat box into an Xc/Yc slice.
GRID_INDEX_DIMS = ("Yc", "Xc")

METHODS = ["eqm", "3dbc-eqm"]  # bias-adjustment methods

MODELS_CMIP5 = [  # rcp26 / rcp45
    "cnrm-r1i1p1-aladin", "ecearth-r12i1p1-cclm", "ecearth-r3i1p1-hirham",
    "hadgem-r1i1p1-rca", "mpi-r1i1p1-cclm", "noresm-r1i1p1-rca",
    "ecearth-r12i1p1-rca", "hadgem-r1i1p1-remo", "mpi-r2i1p1-remo",
    "noresm-r1i1p1-remo",
]

MODELS_CMIP6 = [  # ssp370
    "noresm-r1i1p1f1-hclim", "mpi-r1i1p1f1-racmo", "mpi-r1i1p1f1-icon",
    "mpi-r1i1p1f1-hclim", "miroc-r1i1p1f1-icon", "ecearthveg-r1i1p1f1-hclim",
    "ecearthveg-r1i1p1f1-cclm", "ecearth-r1i1p1f1-racmo",
    "cnrm-r1i1p1f2-racmo", "cnrm-r1i1p1f2-hclim",
]

MODELS_HIST = MODELS_CMIP5 + MODELS_CMIP6

HADGEM_MODELS = {"hadgem-r1i1p1-rca", "hadgem-r1i1p1-remo"}

# scenario -> (models, start_year, default_end_year)
SCENARIOS = {
    "hist":   (MODELS_HIST,  1971, 2020),
    "rcp26":  (MODELS_CMIP5, 2021, 2100),
    "rcp45":  (MODELS_CMIP5, 2021, 2100),
    "ssp370": (MODELS_CMIP6, 2021, 2100),
}


def end_year_for(scenario: str, model: str, default_end: int) -> int:
    """A handful of HadGEM-driven RCP2.6/4.5 runs stop at 2098, not 2100."""
    if scenario in ("rcp26", "rcp45") and model in HADGEM_MODELS:
        return 2098
    return default_end


@dataclass(frozen=True)
class Member:
    """One (bias-adjustment method, GCM-RCM model) ensemble member. Note the
    20 members are 10 GCM-RCM pairs x 2 methods -- NOT independent; keep
    `model` and `method` as separate coordinates downstream so variance can
    be decomposed by source (see handoff notes §2, §7.6)."""

    method: str
    model: str

    @property
    def member_id(self) -> str:
        return f"{self.model}_{self.method}"


def all_members() -> list[Member]:
    models = set(MODELS_HIST)  # union of CMIP5 + CMIP6 == all 20 models
    return [Member(method=m, model=model) for m in METHODS for model in sorted(models)]


def scenario_member_combos() -> list[tuple[str, Member]]:
    """Every (scenario, member) combination that actually exists in the
    archive -- e.g. rcp26 only has the 10 CMIP5-driven members."""
    combos: list[tuple[str, Member]] = []
    for scenario, (models, _y0, _y1) in SCENARIOS.items():
        for method in METHODS:
            for model in models:
                combos.append((scenario, Member(method=method, model=model)))
    return combos


def build_url(method: str, scenario: str, model: str, year: int, base: str = OPENDAP_BASE) -> tuple[str, str]:
    fname = f"{model}_{scenario}_{method}-estobs_disthbv_norway_1km_mrro_daily_{year}.nc4"
    return f"{base.rstrip('/')}/{method}/{scenario}/{model}/{fname}", fname


def years_for(scenario: str, model: str) -> range:
    _models, y0, y1_default = SCENARIOS[scenario]
    return range(y0, end_year_for(scenario, model, y1_default) + 1)
