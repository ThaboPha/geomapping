"""Session-only confirmed public address matches; never alter source geocodes."""
import pandas as pd
from .data import DataSource
from .databricks_source import DatabricksSource


class SessionNetworkSource:
    def __init__(self, source, matches):
        self.source, self.matches = source, matches

    def __getattr__(self, name):
        return getattr(self.source, name)

    def overlay(self, frame):
        frame = frame.copy()
        for number, match in self.matches.items():
            mask = (frame.PracNumDisplay == number) & (frame.DisplayAddress == match['SourceAddress'])
            mask &= frame.Latitude.isna() | frame.Longitude.isna()
            frame.loc[mask, 'Latitude'] = match['Latitude']
            frame.loc[mask, 'Longitude'] = match['Longitude']
            frame.loc[mask, 'MatchLevel'] = match.get('MatchLevel', 'Confirmed public address match; unverified precision')
        frame['Latitude'] = pd.to_numeric(frame.Latitude, errors='coerce')
        frame['Longitude'] = pd.to_numeric(frame.Longitude, errors='coerce')
        return frame

    def network_directory(self, prod=None):
        return self.overlay(self.source.network_directory(prod))

    def network_hospitals(self, prod=None):
        frame = self.network_directory(prod)
        return frame[frame.ProviderCategory == 'Hospital'].copy()

    def alignment(self, prod=None):
        return DatabricksSource.alignment(self, prod)

    def hospital_gaps(self, prod=None):
        return DataSource.hospital_gaps(self, prod)
