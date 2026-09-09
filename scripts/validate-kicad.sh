#!/usr/bin/env bash
set -u -o pipefail

json_string() {
  python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1"
}

project=
# /workspace is the host bind mount. Keep reports after the one-shot validation
# container exits unless the caller explicitly selects another destination.
out=${KICAD_VALIDATION_REPORT_DIR:-/workspace/.kicad-automation/reports}
do_erc=0
do_drc=0
do_gerbers=0
do_drill=0
do_pdf=0
do_bom=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) project=${2:-}; shift 2 ;;
    --out) out=${2:-}; shift 2 ;;
    --erc) do_erc=1; shift ;;
    --drc) do_drc=1; shift ;;
    --gerbers) do_gerbers=1; shift ;;
    --drill) do_drill=1; shift ;;
    --pdf) do_pdf=1; shift ;;
    --bom) do_bom=1; shift ;;
    --all) do_erc=1; do_drc=1; do_gerbers=1; do_drill=1; do_pdf=1; do_bom=1; shift ;;
    *)
      printf '{"status":"error","failure_class":"configuration","error":%s}\n' "$(json_string "unknown argument: $1")" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$project" ]]; then
  printf '{"status":"error","failure_class":"configuration","error":%s}\n' "$(json_string '--project is required')" >&2
  exit 2
fi

mkdir -p "$out" 2>/dev/null || {
  printf '{"status":"error","failure_class":"report_directory","error":%s}\n' "$(json_string "cannot create report directory: $out")" >&2
  exit 2
}

case "$project" in
  *.kicad_pro|*.kicad_sch|*.kicad_pcb) stem=${project%.*} ;;
  *) stem=$project ;;
esac
sch="$stem.kicad_sch"
pcb="$stem.kicad_pcb"
pro="$stem.kicad_pro"

missing=()
for required in "$pro" "$sch" "$pcb"; do
  [[ -f "$required" ]] || missing+=("$required")
done
if [[ ${#missing[@]} -gt 0 ]]; then
  missing_json=$(printf '%s\n' "${missing[@]}" | jq -R -s 'split("\n") | map(select(length > 0))')
  error_path="$out/$(basename "$stem")-validation-error.json"
  jq -cn \
    --arg project "$pro" \
    --arg error "selected project is incomplete" \
    --argjson missing "$missing_json" \
    '{status:"error",failure_class:"project_files_missing",project:$project,error:$error,missing_files:$missing}' \
    >"$error_path"
  cat "$error_path" >&2
  exit 2
fi

base=$(basename "$stem")
cli_log="$out/$base-kicad-cli.log"
erc_json="$out/$base-erc.json"
drc_json="$out/$base-drc.json"
workspace_relative_report_dir=
case "$out" in
  /workspace/*) workspace_relative_report_dir=${out#/workspace/} ;;
esac
: >"$cli_log"

cli_version=
if cli_version=$(kicad-cli version 2>>"$cli_log"); then
  printf '%s\n' "$cli_version" >>"$cli_log"
else
  code=$?
  jq -cn \
    --arg project "$pro" \
    --arg log "$cli_log" \
    --argjson exit_code "$code" \
    '{status:"error",failure_class:"validator_execution",project:$project,log:$log,exit_code:$exit_code,error:"kicad-cli version probe failed"}' \
    >&2
  exit 2
fi

results=()
has_errors=0
has_violations=0
checks_requested=$((do_erc + do_drc))

report_count() {
  local report=$1
  if [[ ! -f "$report" ]]; then
    printf '%s\n' -1
    return
  fi
  jq -r '((.violations // []) | length) + ((.unconnected_items // []) | length) + ((.schematic_parity // []) | length) + ([.sheets[]?.violations[]?] | length)' "$report" 2>/dev/null || printf '%s\n' -1
}

record_check() {
  local name=$1 code=$2 report=$3
  local count report_exists status
  report_exists=false
  count=-1
  if [[ -f "$report" ]]; then
    report_exists=true
    count=$(report_count "$report")
  fi
  status=pass
  if [[ "$code" -ne 0 ]]; then
    if [[ "$count" -gt 0 ]]; then
      status=violations
      has_violations=1
    else
      status=error
      has_errors=1
    fi
  elif [[ "$report_exists" != true || "$count" -lt 0 ]]; then
    status=error
    has_errors=1
  elif [[ "$count" -gt 0 ]]; then
    status=violations
    has_violations=1
  fi
  results+=("$(jq -cn \
    --arg name "$name" \
    --arg status "$status" \
    --arg report "$report" \
    --arg log "$cli_log" \
    --argjson exit_code "$code" \
    --argjson report_exists "$report_exists" \
    --argjson violation_count "$count" \
    '{name:$name,status:$status,exit_code:$exit_code,report:$report,report_exists:$report_exists,violation_count:$violation_count,log:$log}')")
}

run_check() {
  local name=$1 report=$2
  shift 2
  if kicad-cli "$@" >>"$cli_log" 2>&1; then
    code=0
  else
    code=$?
  fi
  record_check "$name" "$code" "$report"
}

record_artifact() {
  local name=$1 path=$2 code=$3
  local status=pass
  if [[ "$code" -ne 0 ]]; then
    status=error
    has_errors=1
  fi
  results+=("$(jq -cn \
    --arg name "$name" \
    --arg status "$status" \
    --arg path "$path" \
    --arg log "$cli_log" \
    --argjson exit_code "$code" \
    '{name:$name,status:$status,exit_code:$exit_code,path:$path,log:$log}')")
}

run_artifact() {
  local name=$1 path=$2
  shift 2
  if kicad-cli "$@" >>"$cli_log" 2>&1; then
    code=0
  else
    code=$?
  fi
  record_artifact "$name" "$path" "$code"
}

if [[ "$do_erc" -eq 1 ]]; then
  run_check erc "$erc_json" sch erc --format json --severity-all --exit-code-violations --output "$erc_json" "$sch"
fi

if [[ "$do_drc" -eq 1 ]]; then
  run_check drc "$drc_json" pcb drc --format json --severity-all --schematic-parity --exit-code-violations --output "$drc_json" "$pcb"
fi

if [[ "$do_gerbers" -eq 1 ]]; then
  dir="$out/gerbers"
  mkdir -p "$dir"
  run_artifact gerbers "$dir" pcb export gerbers --output "$dir" "$pcb"
fi

if [[ "$do_drill" -eq 1 ]]; then
  dir="$out/drill"
  mkdir -p "$dir"
  run_artifact drill "$dir" pcb export drill --output "$dir" "$pcb"
fi

if [[ "$do_pdf" -eq 1 ]]; then
  dir="$out/pdf"
  mkdir -p "$dir"
  if kicad-cli sch export pdf --output "$dir/$base-schematic.pdf" "$sch" >>"$cli_log" 2>&1; then
    pdf_code=0
  else
    pdf_code=$?
  fi
  if kicad-cli pcb export pdf --output "$dir/$base-board.pdf" "$pcb" >>"$cli_log" 2>&1; then
    board_pdf_code=0
  else
    board_pdf_code=$?
  fi
  if [[ "$pdf_code" -eq 0 && "$board_pdf_code" -eq 0 ]]; then
    combined_pdf_code=0
  else
    combined_pdf_code=1
  fi
  record_artifact pdf "$dir" "$combined_pdf_code"
fi

if [[ "$do_bom" -eq 1 ]]; then
  dir="$out/bom"
  mkdir -p "$dir"
  run_artifact bom "$dir/$base-bom.csv" sch export bom --output "$dir/$base-bom.csv" "$sch"
fi

if [[ "$has_errors" -eq 1 ]]; then
  overall_status=error
  overall_code=2
elif [[ "$has_violations" -eq 1 ]]; then
  overall_status=violations
  overall_code=1
elif [[ "$checks_requested" -gt 0 ]]; then
  overall_status=clean
  overall_code=0
else
  overall_status=completed_without_validation
  overall_code=0
fi

if [[ ${#results[@]} -gt 0 ]]; then
  results_json=$(printf '%s\n' "${results[@]}" | jq -s .)
else
  results_json='[]'
fi
jq -cn \
  --arg project "$pro" \
  --arg kicad_version "$cli_version" \
  --arg log "$cli_log" \
  --arg report_dir "$out" \
  --arg workspace_relative_report_dir "$workspace_relative_report_dir" \
  --arg status "$overall_status" \
  --argjson results "$results_json" \
  '{status:$status,project:$project,kicad_version:$kicad_version,report_dir:$report_dir,workspace_relative_report_dir:(if $workspace_relative_report_dir == "" then null else $workspace_relative_report_dir end),log:$log,results:$results}'

exit "$overall_code"
