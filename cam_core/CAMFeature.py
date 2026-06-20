from __future__ import annotations
from cam_core.cam_file import CAMFile

class CAMFeature:
    def __init__(self, name):
        self.name = name
        self.files = []
        self.button = 0
        self.radiobtn = 0
        self.btnitems = []
        self.default_value = False
        self.wildcard = ""
        self._enabled = False

    def add_CAM_file(self, cfile: CAMFile):
        self.files.append(cfile)

    def get_CAM_files(self):
        return self.files

    def set_radiobtn(self, button_id):
        self.radiobtn = button_id

    def get_radiobtn(self):
        return self.radiobtn

    def set_enabled(self):
        self._enabled = True

    def clear_enabled(self):
        self._enabled = False

    def get_enabled(self):
        return self._enabled

    def get_name(self):
        return self.name