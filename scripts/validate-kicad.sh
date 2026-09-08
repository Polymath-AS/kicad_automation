#!/usr/bin/env bash
set -euo pipefail

die() { printf '{"error":%s}\n' "$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$*")" >&2; exit 2; }
json_string() { python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1"; }

project=
out=/runtime/reports
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
    *) die "unknown argument: $1" ;;
  esac
done

[[ -n "$project" ]] || die "--project is required"
case "$project" in
  *.kicad_pro|*.kicad_sch|*.kicad_pcb) stem=${project%.*} ;;
  *) stem=$project ;;
esac
sch="$stem.kicad_sch"
pcb="$stem.kicad_pcb"
pro="$stem.kicad_pro"
[[ -f "$sch" ]] || die "schematic not found: $sch"
[[ -f "$pcb" ]] || die "board not found: $pcb"
[[ -f "$pro" ]] || die "project not found: $pro"

mkdir -p "$out"
base=$(basename "$stem")
cli_log="$out/$base-kicad-cli.log"
: >"$cli_log"
erc_json="$out/$base-erc.json"
drc_json="$out/$base-drc.json"
exit_code=0
results=()

run_cli() {
  kicad-cli "$@" >>"$cli_log" 2>&1
}

record() {
  local name=$1 code=$2 path=$3
  results+=("{\"name\":$(json_string "$name"),\"exit_code\":$code,\"path\":$(json_string "$path")}")
  if [[ $code -ne 0 ]]; then exit_code=$code; fi
}

if [[ $do_erc -eq 1 ]]; then
  set +e
  run_cli sch erc --format json --severity-all --exit-code-violations --output "$erc_json" "$sch"
  code=$?
  set -e
  record erc "$code" "$erc_json"
fi

if [[ $do_drc -eq 1 ]]; then
  set +e
  run_cli pcb drc --format json --severity-all --schematic-parity --exit-code-violations --output "$drc_json" "$pcb"
  code=$?
  set -e
  record drc "$code" "$drc_json"
fi

if [[ $do_gerbers -eq 1 ]]; then
  dir="$out/gerbers"
  mkdir -p "$dir"
  run_cli pcb export gerbers --output "$dir" "$pcb"
  record gerbers 0 "$dir"
fi

if [[ $do_drill -eq 1 ]]; then
  dir="$out/drill"
  mkdir -p "$dir"
  run_cli pcb export drill --output "$dir" "$pcb"
  record drill 0 "$dir"
fi

if [[ $do_pdf -eq 1 ]]; then
  dir="$out/pdf"
  mkdir -p "$dir"
  run_cli sch export pdf --output "$dir/$base-schematic.pdf" "$sch"
  run_cli pcb export pdf --output "$dir/$base-board.pdf" "$pcb"
  record pdf 0 "$dir"
fi

if [[ $do_bom -eq 1 ]]; then
  dir="$out/bom"
  mkdir -p "$dir"
  run_cli sch export bom --output "$dir/$base-bom.csv" "$sch"
  record bom 0 "$dir/$base-bom.csv"
fi

printf '{"project":%s,"kicad_version":%s,"log":%s,"results":[%s]}\n' \
  "$(json_string "$pro")" \
  "$(json_string "$(kicad-cli version)")" \
  "$(json_string "$cli_log")" \
  "$(IFS=,; echo "${results[*]}")"

exit "$exit_code"
