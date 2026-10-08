#!/bin/bash
# 下载 Klima i Norge 2025 数据集中 mrro(径流)变量的全部原始文件(未裁剪区域)
# 覆盖两种偏差校正方法 x 四种排放情景 x 所有对应气候模式 x 所有年份

BASE_URL="https://thredds.met.no/thredds/fileServer/KSS/Klima_i_Norge/utgave2025/DailyTimeSeries/mrro"
OUT_DIR="/cluster/work/projects/nn10014k/luli/kin2025/mrro/"   # 改成你在 NIRD 上想要的输出路径
LOG_FILE="download_mrro_full.log"

mkdir -p "$OUT_DIR"

METHODS=("eqm" "3dbc-eqm")

MODELS_CMIP5=("cnrm-r1i1p1-aladin" "ecearth-r12i1p1-cclm" "ecearth-r3i1p1-hirham" \
              "hadgem-r1i1p1-rca" "mpi-r1i1p1-cclm" "noresm-r1i1p1-rca" \
              "ecearth-r12i1p1-rca" "hadgem-r1i1p1-remo" "mpi-r2i1p1-remo" \
              "noresm-r1i1p1-remo")

MODELS_CMIP6=("noresm-r1i1p1f1-hclim" "mpi-r1i1p1f1-racmo" "mpi-r1i1p1f1-icon" \
              "mpi-r1i1p1f1-hclim" "miroc-r1i1p1f1-icon" "ecearthveg-r1i1p1f1-hclim" \
              "ecearthveg-r1i1p1f1-cclm" "ecearth-r1i1p1f1-racmo" \
              "cnrm-r1i1p1f2-racmo" "cnrm-r1i1p1f2-hclim")

MODELS_HIST=("${MODELS_CMIP5[@]}" "${MODELS_CMIP6[@]}")

is_hadgem() {
  [[ "$1" == "hadgem-r1i1p1-rca" || "$1" == "hadgem-r1i1p1-remo" ]]
}

download_group() {
  local scenario=$1; shift
  local y0=$1; shift
  local y1_default=$1; shift
  local models=("$@")

  for method in "${METHODS[@]}"; do
    for model in "${models[@]}"; do
      local y1=$y1_default
      if [[ "$scenario" == "rcp26" || "$scenario" == "rcp45" ]] && is_hadgem "$model"; then
        y1=2098
      fi
      local outdir="$OUT_DIR/$method/$scenario/$model"
      mkdir -p "$outdir"
      for year in $(seq "$y0" "$y1"); do
        fname="${model}_${scenario}_${method}-estobs_disthbv_norway_1km_mrro_daily_${year}.nc4"
        url="${BASE_URL}/${method}/${scenario}/${model}/${fname}"
        # Skip files that are already complete. thredds.met.no answers a Range
        # request past the end of a file with "206" and an empty body instead
        # of "416", so `wget -c` on a complete file retries 20 times (~2.5 min)
        # and then reports FAIL (confirmed 2026-10-08). Partial files still
        # resume with wget -c below.
        remote_size=$(curl -sfI "$url" | awk 'tolower($1)=="content-length:" {print $2}' | tr -d '\r')
        local_size=$(stat -L -c %s "$outdir/$fname" 2>/dev/null || echo 0)
        if [[ -n "$remote_size" && "$local_size" == "$remote_size" ]]; then
          echo "$(date '+%F %T') SKIP complete $fname" >> "$LOG_FILE"
          sleep 1
          continue
        fi
        echo "$(date '+%F %T') downloading $fname" >> "$LOG_FILE"
        wget -c -q -O "$outdir/$fname" "$url" \
          && echo "$(date '+%F %T') OK $fname" >> "$LOG_FILE" \
          || echo "$(date '+%F %T') FAIL $fname" >> "$LOG_FILE"
        sleep 1   # 礼貌性延迟,避免对服务器造成压力,遵守网站使用条款
      done
    done
  done
}

download_group "hist"   1971 2020 "${MODELS_HIST[@]}"
download_group "rcp26"  2021 2100 "${MODELS_CMIP5[@]}"
download_group "rcp45"  2021 2100 "${MODELS_CMIP5[@]}"
download_group "ssp370" 2021 2100 "${MODELS_CMIP6[@]}"

echo "All downloads complete"
