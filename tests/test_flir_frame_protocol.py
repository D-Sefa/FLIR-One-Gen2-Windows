import ast
import pathlib
import struct
import unittest


SOURCE = pathlib.Path(__file__).resolve().parents[1] / "work" / "flir_iap2_frame.py"
MAGIC = b"\xef\xbe\x00\x00"


def load_protocol_function(name):
    """Load one real production function without starting the USB main loop."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    functions = {
        node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    if name not in functions:
        raise AssertionError(f"production function {name!r} is missing")
    module = ast.Module(body=[functions[name]], type_ignores=[])
    namespace = {"struct": struct, "FRAME_MAGIC": MAGIC}
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), namespace)
    return namespace[name]


def make_record(*, frame_size, thermal_size, jpeg_size, status_size, payload):
    header = (
        MAGIC
        + b"\x00\x00\x00\x00"
        + struct.pack("<4I", frame_size, thermal_size, jpeg_size, status_size)
        + b"\x00\x00\x00\x00"
    )
    return header + payload


class Ep85FrameBoundaryTests(unittest.TestCase):
    def test_waits_for_declared_frame_size_not_section_sum(self):
        """A residual payload must not be mistaken for the next frame."""
        pop_frame = load_protocol_function("pop_complete_ep85_frame")
        payload = b"T" * 8 + b"S" * 4 + b"R" * 5
        full_record = make_record(
            frame_size=len(payload),
            thermal_size=8,
            jpeg_size=0,
            status_size=4,
            payload=payload,
        )
        stream = bytearray(full_record[:-1])

        self.assertIsNone(pop_frame(stream))
        self.assertEqual(stream, full_record[:-1])

        stream.extend(full_record[-1:])
        record, header = pop_frame(stream)

        self.assertEqual(record, full_record)
        self.assertEqual(header, (17, 8, 0, 4))
        self.assertEqual(stream, b"")

    def test_rejects_sections_larger_than_declared_frame(self):
        """Corrupt section sizes must not splice bytes from the next record."""
        pop_frame = load_protocol_function("pop_complete_ep85_frame")
        bad = make_record(
            frame_size=8,
            thermal_size=8,
            jpeg_size=4,
            status_size=0,
            payload=b"X" * 8,
        )
        good_payload = b"T" * 6
        good = make_record(
            frame_size=len(good_payload),
            thermal_size=6,
            jpeg_size=0,
            status_size=0,
            payload=good_payload,
        )
        stream = bytearray(bad + good)

        record, header = pop_frame(stream)

        self.assertEqual(record, good)
        self.assertEqual(header, (6, 6, 0, 0))
        self.assertEqual(stream, b"")

    def test_scans_full_record_for_jpeg_when_header_size_is_zero(self):
        """Unlabelled JPEG data in residual bytes remains observable."""
        inspect_frame = load_protocol_function("inspect_ep85_frame")
        hidden_jpeg = b"\xff\xd8JPEG-DATA\xff\xd9"
        payload = b"T" * 8 + b"S" * 4 + hidden_jpeg
        record = make_record(
            frame_size=len(payload),
            thermal_size=8,
            jpeg_size=0,
            status_size=4,
            payload=payload,
        )

        info = inspect_frame(record)

        self.assertEqual(info["residual"], len(hidden_jpeg))
        self.assertEqual(info["jpeg_scan_scope"], "full-record")
        self.assertEqual(info["jpeg_soi"], 40)
        self.assertEqual(info["jpeg_eoi"], 51)


if __name__ == "__main__":
    unittest.main()
