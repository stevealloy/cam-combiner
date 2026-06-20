from __future__ import annotations
from cam_core.CAMFeature import CAMFeature


class FeatureBlock:
    def __init__(self, name, subdir):
        self.features = []
        self.CAM_features = []
        self.name = name
        self.subdir = subdir
        self.fbwin = 0

    def add_CAM_feature(self, cft: CAMFeature):
        self.features.append(cft)

    def get_CAM_features(self):
        return self.features

    def add_CAM_file(self, cft: CAMFeature):
        self.CAM_features.append(cft)

    def get_CAM_files(self):
        return self.CAM_features

    def get_name(self):
        return self.name