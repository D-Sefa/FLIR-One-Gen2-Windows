"""Archive fixtures are real F1D1 records, not mocks of the archive reader."""
import datetime as dt
import importlib.util
import pathlib
import sqlite3
import struct
import sys
import tempfile
import unittest
import zlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'work'))


def make_archive(folder, stamps):
    con = sqlite3.connect(folder/'history.sqlite3')
    con.execute('CREATE TABLE frames(ts REAL PRIMARY KEY,file TEXT,offset INTEGER,raw_size INTEGER,comp_size INTEGER)')
    with (folder/'fixture.f1dvr').open('wb') as f:
        for n, ts in enumerate(stamps):
            values = [7000+n*10]*19200
            values[2*160+159-3] = 8000+n*20  # display x=2,y=3
            raw = struct.pack('<19200H', *values)
            comp = zlib.compress(raw)
            offset = f.tell()
            f.write(struct.pack('<4sQII', b'F1D1', int(ts*1e9), len(raw), len(comp)))
            f.write(comp)
            con.execute('INSERT INTO frames VALUES(?,?,?,?,?)', (ts,'fixture.f1dvr',offset,len(raw),len(comp)))
    con.commit()
    con.close()


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('flir_gallery'), 'RAW recording gallery backend is missing')
        import flir_gallery
        self.g = flir_gallery
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = pathlib.Path(self.tmp.name)
        self.start = dt.datetime(2026,10,2,23,59,58).timestamp()
        make_archive(self.folder, [self.start, self.start+1, self.start+2, self.start+3, self.start+100])
        self.store = self.g.ArchiveStore(self.folder)

    def test_calendar_splits_midnight_and_preserves_every_frame(self):
        sessions = self.store.sessions()
        self.assertEqual([s['count'] for s in sessions], [2,2,1])
        self.assertEqual([s['date'] for s in sessions], ['2026-10-02','2026-10-03','2026-10-03'])
        self.assertEqual(len(self.store.sessions('2026-10-03','2026-10-03')), 2)
        self.assertEqual(self.store.sessions('2026-10-04','2026-10-04'), [])

    def test_nearest_read_is_bounded_and_does_not_jump_gaps(self):
        self.assertEqual(self.store.nearest(self.start+.2, self.start,self.start+1)[0], self.start)
        self.assertIsNone(self.store.at_time(self.start+50))
        self.assertEqual(self.store.at_time(self.start+2)[0],self.start+2)
        self.assertIsNone(self.store.nearest(self.start, self.start+10,self.start+20))

    def test_reanalysis_uses_raw_at_new_points_and_keeps_raw_unchanged(self):
        before = (self.folder/'fixture.f1dvr').read_bytes()
        series = self.store.analyze(self.start,self.start+3, [('P1',2,3)],(.95,20.,0.),False)
        self.assertEqual(len(series['P1']), 4)
        self.assertEqual(series['P1'][0][0], self.start)
        self.assertGreater(series['P1'][-1][1], series['P1'][0][1])
        self.assertAlmostEqual(series['MAX'][0][1], series['P1'][0][1])
        offset = self.store.analyze(self.start,self.start+3, [('P1',2,3)],(.95,20.,5.),False)
        self.assertAlmostEqual(offset['P1'][0][1]-series['P1'][0][1], 5.)
        self.assertEqual((self.folder/'fixture.f1dvr').read_bytes(), before)

    def test_corrupt_record_is_not_shown_as_valid(self):
        (self.folder/'fixture.f1dvr').write_bytes(b'bad')
        self.assertIsNone(self.store.nearest(self.start))

    def test_invalid_dates_report_error(self):
        with self.assertRaises(ValueError):self.store.sessions('2026-02-30','2026-10-03')
        with self.assertRaises(ValueError):self.store.sessions('2026-10-04','2026-10-03')


if __name__ == '__main__':unittest.main()
