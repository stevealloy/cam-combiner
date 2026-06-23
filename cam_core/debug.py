try:
    import dearpygui.dearpygui as dpg
except ModuleNotFoundError:
    dpg = None

def debug_dump_all(base_dir: str,
                   params: dict,
                   files,#: list[CAMFile],
                   features,#: list[CAMFeature],
                   featureblocks) -> str: #: list[FeatureBlock]) -> str:
    ret_string = "================ PARAMETERS ================\n"

    for k in sorted(params.keys()):
        try:
            ret_string += f" - {k} = {params[k]}\n"
        except Exception as e:
            ret_string += f" - {k} = <err {e}>\n"

    ret_string += "================ DIRECTORY LISTING ================\n"
    for f in files:
        ret_string += f" - {f.name}\n"

    ret_string += "================ FEATURE BLOCKS ================\n"
    for f in featureblocks:
        ret_string += f" - {f.name}\n"

    ret_string += "================ FEATURES ================\n"
    for f in features:
        ret_string += f" - {f.name}\n"

    return ret_string

def debug_print(*args):
    message = " ".join(str(a) for a in args)
    print("[debug] " + message)
    try:
        current_text = dpg.get_value("Log")
        dpg.set_value("Log", current_text + message + "\n")
        max_scroll = dpg.get_y_scroll_max("Log_window")
        dpg.set_y_scroll("Log_window", max_scroll)
    except Exception:
        pass


def debug_dump_params_and_dir(base_dir: str, params: dict, files) -> None:
    print("================ PARAMETERS ================")
    for k in sorted(params.keys()):
        print(f" - {k} = {params[k]}")
    print("================ DIRECTORY LISTING ================")
    for f in files:
        name = f.name if hasattr(f, "name") else str(f)
        print(f" - {name}")
