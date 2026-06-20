import argparse, os, sys, json
from cam_core.version import VERSION, CLI_BANNER, APP_BANNER
from cam_core.jsonc_loader import load_config_file, normalize_legacy
from cam_core.planner import plan, scan_files
from cam_core.xls_mode import process_xls
from cam_core.debug import debug_dump_params_and_dir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", help="Base directory containing .nc files")
    ap.add_argument("--config", help="Path to fixture_config (JSONC/YAML). Defaults to <base>/fixture_config.txt")
    ap.add_argument("--xlsx", help="Run XLS batch mode on given workbook")
    ap.add_argument("--verbose", action="store_true", default=False)
    args = ap.parse_args()

    print(CLI_BANNER)
    print("="*40)
    print(APP_BANNER)
    print("="*40)

    if args.xlsx:
        print("[xls] input:", args.xlsx)
        # process
        rc = process_xls(args.xlsx, plan)
        print("[xls exit] status=xls rc={}".format(rc))
        sys.exit(rc)
        return


    if not args.base:
        print("CLI: must specify base.")
        return

    base = args.base
    cfg_path = args.config or os.path.join(base, "fixture_config.txt")
    print(f"[paths] base='{os.path.abspath(base)}'  cfg='{os.path.abspath(cfg_path)}'")

    try:
        cfg = normalize_legacy(load_config_file(cfg_path))
    except Exception as e:
        print(f"[warn] failed to load config: {e}")
        cfg = {"parameters": [], "outputs": [], "base_selection": {"input_file_base_names": []}}

    params = {p["name"]: p.get("default") for p in cfg.get("parameters",[]) if isinstance(p, dict) and p.get("name")}

    files, fblocks, features, tools = scan_files(base)
    if args.verbose:
        debug_dump_params_and_dir(base, params, files)

    resolved, by_step = plan(cfg, params, files, base, fblocks, [], verbose=args.verbose)
    print("[exit] status=ok")

if __name__ == "__main__":
    main()
