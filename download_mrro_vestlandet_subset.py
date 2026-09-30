"""
下载 Klima i Norge 2025 数据集中 mrro(径流)变量,
仅裁剪 Vestlandet 区域(Xc: 45:175, Yc: 1165:1290),
覆盖两种偏差校正方法 x 四种排放情景 x 所有对应气候模式 x 所有年份。

依赖: xarray, netCDF4 (需要支持 OPeNDAP 的 libnetcdf), numpy
建议在 NIRD 上用 conda 环境安装: conda install -c conda-forge xarray netcdf4
"""

import os
import time
import logging
import xarray as xr

# ---------- 配置 ----------
BASE_URL = "https://thredds.met.no/thredds/dodsC/KSS/Klima_i_Norge/utgave2025/DailyTimeSeries/mrro"
OUT_DIR = "./vestlandet_mrro"   # 改成你在 NIRD 上想要的输出路径

# Vestlandet 区域网格索引范围(含边界,已加余量)
XC_SLICE = slice(45, 176)     # Xc 45..175
YC_SLICE = slice(1165, 1291)  # Yc 1165..1290

METHODS = ["eqm", "3dbc-eqm"]

MODELS_CMIP5 = [  # 用于 rcp26 / rcp45
    "cnrm-r1i1p1-aladin", "ecearth-r12i1p1-cclm", "ecearth-r3i1p1-hirham",
    "hadgem-r1i1p1-rca", "mpi-r1i1p1-cclm", "noresm-r1i1p1-rca",
    "ecearth-r12i1p1-rca", "hadgem-r1i1p1-remo", "mpi-r2i1p1-remo",
    "noresm-r1i1p1-remo",
]

MODELS_CMIP6 = [  # 用于 ssp370
    "noresm-r1i1p1f1-hclim", "mpi-r1i1p1f1-racmo", "mpi-r1i1p1f1-icon",
    "mpi-r1i1p1f1-hclim", "miroc-r1i1p1f1-icon", "ecearthveg-r1i1p1f1-hclim",
    "ecearthveg-r1i1p1f1-cclm", "ecearth-r1i1p1f1-racmo",
    "cnrm-r1i1p1f2-racmo", "cnrm-r1i1p1f2-hclim",
]

MODELS_HIST = MODELS_CMIP5 + MODELS_CMIP6  # hist 包含全部20个模式

HADGEM_MODELS = {"hadgem-r1i1p1-rca", "hadgem-r1i1p1-remo"}

# 每个情景对应: (模式列表, 起始年, 默认结束年)
SCENARIOS = {
    "hist":   (MODELS_HIST,  1971, 2020),
    "rcp26":  (MODELS_CMIP5, 2021, 2100),
    "rcp45":  (MODELS_CMIP5, 2021, 2100),
    "ssp370": (MODELS_CMIP6, 2021, 2100),
}

SLEEP_BETWEEN_REQUESTS = 1.0  # 秒,避免给服务器造成压力(遵守网站使用条款)

logging.basicConfig(
    filename="download_mrro_vestlandet.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def end_year_for(scenario, model, default_end):
    if scenario in ("rcp26", "rcp45") and model in HADGEM_MODELS:
        return 2098
    return default_end


def build_url(method, scenario, model, year):
    fname = f"{model}_{scenario}_{method}-estobs_disthbv_norway_1km_mrro_daily_{year}.nc4"
    return f"{BASE_URL}/{method}/{scenario}/{model}/{fname}", fname


def download_one(method, scenario, model, year):
    url, fname = build_url(method, scenario, model, year)
    out_subdir = os.path.join(OUT_DIR, method, scenario, model)
    os.makedirs(out_subdir, exist_ok=True)
    out_path = os.path.join(out_subdir, fname)

    if os.path.exists(out_path):
        logging.info(f"SKIP existing: {out_path}")
        return

    try:
        ds = xr.open_dataset(url)
        subset = ds.isel(Xc=XC_SLICE, Yc=YC_SLICE)
        # 只保留 mrro 及其必要坐标变量(lat/lon/time/time_bnds 会随坐标自动保留)
        subset = subset[["mrro"]]
        subset.to_netcdf(out_path)
        subset.close()
        ds.close()
        logging.info(f"OK: {out_path}")
    except Exception as e:
        logging.error(f"FAIL: {url} -> {e}")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    tasks = []
    for method in METHODS:
        for scenario, (models, y0, y1_default) in SCENARIOS.items():
            for model in models:
                y1 = end_year_for(scenario, model, y1_default)
                for year in range(y0, y1 + 1):
                    tasks.append((method, scenario, model, year))

    print(f"Total files to download: {len(tasks)}")
    for i, (method, scenario, model, year) in enumerate(tasks, 1):
        print(f"[{i}/{len(tasks)}] {method} {scenario} {model} {year}")
        download_one(method, scenario, model, year)
        time.sleep(SLEEP_BETWEEN_REQUESTS)


if __name__ == "__main__":
    main()
