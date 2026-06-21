import os

class Tool:
    def __init__(self, tnum, tdescr: str):
        self.tnum = int(tnum)
        self.tdesc:str = tdescr
        self.files = []  # Would be CAMFile, but circular reference, so use generic
        self.error: bool = False
        self.warning: bool = False

    def __repr__(self):
        rstr = ""
        if self.error:
            rstr = "ERROR:\t" + self.error
        elif self.warning:
            rstr = "WARNING:\t"
        rstr = rstr + "\t"

        dform = f"{self.tdesc:.20}"
        rstr = rstr + "T#" + f"{self.tnum:02d}\t" + dform
        return rstr

    def get_tool_num(self)->int:
        return self.tnum

    def get_desc(self)->str:
        return self.tdesc

    def add_file(self, file):
        self.files.append(file)

    def get_files(self)->[]:
        return self.files

    def set_error(self, val:str):
        self.error = val

    def set_warning(self, val:str):
        # if there is already an error pending, ignore the warning.
        if self.error:
            return
        self.warning = val

    def get_error(self)->str:
        return self.error

    def get_warning(self)->str:
        return self.warning