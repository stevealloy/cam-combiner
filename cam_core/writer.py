from cam_core.cam_file import CAMFile


def write_output_file(cfile: CAMFile, fname: str, output_file,
                      start_unit: int, num_units: int, mirror: bool,
                      tnum, suppress_end_code: bool,
                      cline: float, cline_delta: float, direction: str):
    output_file.write("( BEGIN FILE " + fname + "TNUM: " + str(tnum) + " )\n")
    output_file.write("( Lefty:" + str(mirror) + " Nunits:" + str(num_units) + " )\n")
    output_file.write("( cline: " + str(cline) + " delta:" + str(cline_delta) + " )\n")
    output_file.write("( start_unit: " + str(start_unit) + " num_units: " + str(num_units) + ")\n")

    for line in cfile.get_output(mirror, cline, cline_delta, start_unit, num_units, direction, suppress_end_code):
        output_file.write(line)

    output_file.write("( END FILE " + fname + " )\n")
