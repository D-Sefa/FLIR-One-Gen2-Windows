import datetime
import json
import os
import pathlib
import struct
import sys
import time
import zlib

sys.path.insert(0, str(pathlib.Path(__file__).with_name("pydeps")))

import libusb_package
import usb.core
import usb.util


VID, PID, INTERFACE = 0x09CB, 0x1996, 0
EP_IN, EP_OUT = 0x81, 0x02
DETECT = bytes.fromhex("ff 55 02 00 ee 10")
START_IDENTIFICATION = bytes.fromhex("40 40 00 06 1d 00")
CAPTURE_DIR = pathlib.Path(__file__).with_name("captures")
CAPTURE_DIR.mkdir(exist_ok=True)
LIVE_IMAGE = pathlib.Path(__file__).resolve().parents[1] / "outputs" / "flir-live.ppm"
LIVE_RAW = pathlib.Path(__file__).resolve().parents[1] / "outputs" / "flir-live.raw16"
LIVE_VISUAL = pathlib.Path(__file__).resolve().parents[1] / "outputs" / "flir-live-visible.jpg"
LIVE_STATUS = pathlib.Path(__file__).resolve().parents[1] / "outputs" / "flir-live-status.json"
FRAME_MAGIC = b"\xef\xbe\x00\x00"
_last_good_span = None
_ffc_skip_frames = 0
_ffc_cooldown_until = 0.0


def publish_thermal_frame(record):
    """Convert one complete EP85 record to a 4x false-colour PPM image."""
    global _last_good_span, _ffc_skip_frames, _ffc_cooldown_until
    values = []
    for y in range(120):
        row_offset = 32 + y * 328
        values.extend(struct.unpack_from("<80H", record, row_offset))
        values.extend(struct.unpack_from("<80H", record, row_offset + 164))
    # A handful of invalid/dead pixels can momentarily jump to 10k-60k and
    # crush the whole picture into blue.  Use robust scene percentiles for
    # display while preserving the original 16-bit samples internally.
    ordered = sorted(values)
    lo = ordered[len(ordered) * 2 // 100]
    hi = ordered[len(ordered) * 98 // 100]
    span = max(1, hi - lo)
    # During automatic flat-field correction the shutter covers the sensor.
    # Those nearly-uniform frames are calibration data, not scene data.  Hold
    # the last clean picture instead of displaying/recording the visible flash.
    sudden_flat = (
        time.monotonic() >= _ffc_cooldown_until
        and
        _last_good_span is not None
        and _last_good_span >= 120
        and span < max(45, _last_good_span * 0.28)
    )
    if sudden_flat:
        _ffc_skip_frames = 6
        _ffc_cooldown_until = time.monotonic() + 8.0
        print(
            f"[{now()}] FFC shutter frame ignored (span={span}, previous={_last_good_span})",
            flush=True,
        )
        return None
    if _ffc_skip_frames:
        _ffc_skip_frames -= 1
        if not _ffc_skip_frames:
            _last_good_span = span
        print(f"[{now()}] FFC settling frame ignored", flush=True)
        return None
    _last_good_span = span
    if os.environ.get("FLIR_SKIP_PPM") == "1":
        # The desktop viewer renders RAW16 itself; avoid a second false-colour
        # render and disk write in the USB reader's critical path.
        atomic_write(LIVE_RAW, struct.pack("<19200H", *values))
        return lo, hi
    rgb = bytearray(120 * 160 * 3)
    for y in range(120):
        for x in range(160):
            v = max(0, min(255, (values[y * 160 + x] - lo) * 255 // span))
            red = min(255, max(0, 3 * v - 256))
            green = min(255, max(0, 3 * v - 128)) - max(0, 3 * v - 512)
            blue = min(255, max(0, 255 - 3 * v))
            out = (y + (159 - x) * 120) * 3
            rgb[out : out + 3] = bytes((red, green, blue))
    ppm = b"P6\n120 160\n255\n" + bytes(rgb)
    atomic_write(LIVE_RAW, struct.pack("<19200H", *values))
    atomic_write(LIVE_IMAGE, ppm)
    return lo, hi


def atomic_write(path, data):
    # Windows refuses os.replace() while another process has the destination
    # open without FILE_SHARE_DELETE.  Direct overwrite is safe here: the
    # viewer validates the exact raw-frame length and simply skips a partial
    # read.  Most importantly, a display-side file lock can never kill USB.
    for attempt in range(40):
        try:
            path.write_bytes(data)
            return
        except PermissionError:
            if attempt == 39:
                print(f"[{now()}] Output busy; dropping one published frame: {path.name}", flush=True)
                return
            time.sleep(0.005)


def usb_write(dev, endpoint, data, timeout=500):
    """Retry transient WinUSB write timeouts without tearing down iAP2."""
    for attempt in range(4):
        try:
            return dev.write(endpoint, data, timeout=timeout)
        except usb.core.USBError as exc:
            if getattr(exc, "errno", None) != 10060 or attempt == 3:
                raise
            print(
                f"[{now()}] RECOVERY transient USB write timeout; retry {attempt + 1}/3",
                flush=True,
            )
            time.sleep(0.03 * (attempt + 1))


def pop_complete_ep85_frame(frame_stream):
    """Remove and return one complete FrameSize-delimited EP85 record."""
    while True:
        start = frame_stream.find(FRAME_MAGIC)
        if start < 0:
            if len(frame_stream) > len(FRAME_MAGIC) - 1:
                del frame_stream[: -(len(FRAME_MAGIC) - 1)]
            return None
        if start:
            del frame_stream[:start]
        if len(frame_stream) < 28:
            return None

        frame_size, thermal_size, jpeg_size, status_size = struct.unpack_from(
            "<4I", frame_stream, 8
        )
        known_payload = thermal_size + jpeg_size + status_size
        if frame_size == 0 or known_payload > frame_size:
            # The header cannot describe a valid record. Drop this magic and
            # resynchronise instead of consuming bytes from the next frame.
            del frame_stream[: len(FRAME_MAGIC)]
            continue

        total = 28 + frame_size
        if len(frame_stream) < total:
            return None

        record = bytes(frame_stream[:total])
        del frame_stream[:total]
        return record, (frame_size, thermal_size, jpeg_size, status_size)


def inspect_ep85_frame(record):
    """Return full-record diagnostics, including an optional JPEG scan."""
    if len(record) < 28:
        raise ValueError("short frame record")
    frame_size, thermal_size, jpeg_size, status_size = struct.unpack_from(
        "<4I", record, 8
    )
    known_payload = thermal_size + jpeg_size + status_size
    if known_payload > frame_size:
        raise ValueError(
            f"section sizes exceed FrameSize: {known_payload} > {frame_size}"
        )
    expected = 28 + frame_size
    if len(record) < expected:
        raise ValueError(f"frame length mismatch: {len(record)} < {expected}")

    if jpeg_size:
        scan_start = 28 + thermal_size
        scan_end = scan_start + jpeg_size
        scan_scope = "declared-jpeg"
    else:
        scan_start = 0
        scan_end = expected
        scan_scope = "full-record"
    soi = record.find(b"\xff\xd8", scan_start, scan_end)
    eoi = record.find(b"\xff\xd9", soi + 2, scan_end) if soi >= 0 else -1

    return {
        "header_hex": record[:28].hex(" "),
        "frame_size": frame_size,
        "thermal_size": thermal_size,
        "jpeg_size": jpeg_size,
        "status_size": status_size,
        "residual": frame_size - known_payload,
        "jpeg_scan_scope": scan_scope,
        "jpeg_soi": soi,
        "jpeg_eoi": eoi,
    }


def publish_frame(record):
    """Publish thermal samples plus the optional 640x480 visual JPEG."""
    if len(record) < 28:
        raise ValueError("short frame record")
    frame_size, thermal_size, jpeg_size, status_size = struct.unpack_from("<4I", record, 8)
    payload_size = thermal_size + jpeg_size + status_size
    if payload_size > frame_size:
        raise ValueError(
            f"section sizes exceed FrameSize: {payload_size} > {frame_size}"
        )
    expected = 28 + frame_size
    if len(record) < expected:
        raise ValueError(f"frame length mismatch: {len(record)} < {expected}")
    if frame_size > payload_size:
        print(
            f"[{now()}] FRAME size disagreement: declared={frame_size} "
            f"sections={payload_size} residual={frame_size - payload_size}",
            flush=True,
        )
    jpeg_start = 28 + thermal_size
    jpeg_end = jpeg_start + jpeg_size
    status_start = jpeg_end
    status_end = status_start + status_size
    if jpeg_size and jpeg_end <= len(record):
        jpeg = record[jpeg_start:jpeg_end]
        soi, eoi = jpeg.find(b"\xff\xd8"), jpeg.rfind(b"\xff\xd9")
        if soi >= 0 and eoi > soi:
            atomic_write(LIVE_VISUAL, jpeg[soi:eoi + 2])
    if status_size and status_end <= len(record):
        publish_status_message(record[status_start:status_end])
    thermal_result = publish_thermal_frame(record)
    if thermal_result is None:
        return None
    lo, hi = thermal_result
    return lo, hi, jpeg_size, status_size


def publish_status_message(payload):
    """Expose battery/charging telemetry to the desktop viewer."""
    marker = payload.find(b'{"type"')
    if marker < 0:
        return
    end = payload.find(b"\x00", marker)
    if end < 0:
        return
    try:
        message = json.loads(payload[marker:end].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return
    if message.get("type") not in {
        "batteryVoltageUpdate", "batteryChargingStateUpdate",
        "batteryChargingCurrentUpdate", "sledInformation",
    }:
        return
    state = {}
    try:
        state = json.loads(LIVE_STATUS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    state[message["type"]] = message.get("data", {})
    state["updated"] = time.time()
    atomic_write(LIVE_STATUS, json.dumps(state, ensure_ascii=False).encode("utf-8"))


def now():
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


def checksum(data):
    return (-sum(data)) & 0xFF


def link_packet(control, seq, ack, session=0, payload=b""):
    length = 9 if not payload else len(payload) + 10
    head = b"\xff\x5a" + length.to_bytes(2, "big") + bytes([control, seq, ack, session])
    packet = head + bytes([checksum(head)])
    if payload:
        packet += payload + bytes([checksum(payload)])
    return packet


def rbp_config_packet(packet_type, data=None, protocol_version=1):
    """Build the Rosebud config frame used by librbp (no device mutation)."""
    import json

    body = json.dumps(
        {"type": packet_type, "data": data or {}}, separators=(",", ":")
    ).encode("utf-8") + b"\x00"
    header12 = struct.pack("<III", 0x1CC, protocol_version, len(body))
    return header12 + struct.pack("<I", zlib.crc32(header12) & 0xFFFFFFFF) + body


def parse_link(packet):
    if len(packet) < 9 or packet[:2] != b"\xff\x5a":
        raise ValueError("bad iAP2 marker")
    if int.from_bytes(packet[2:4], "big") != len(packet):
        raise ValueError("bad iAP2 length")
    if sum(packet[:9]) & 0xFF:
        raise ValueError("bad iAP2 header checksum")
    payload = b""
    if len(packet) > 9:
        payload = packet[9:-1]
        if (sum(payload) + packet[-1]) & 0xFF:
            raise ValueError("bad iAP2 payload checksum")
    return packet[4], packet[5], packet[6], packet[7], payload


def extract_transport_items(stream):
    """Recover DETECT/iAP2 packets even when WinUSB prefixes stray frame bytes."""
    items = []
    while stream:
        detect_at = stream.find(DETECT)
        iap_at = stream.find(b"\xff\x5a")
        positions = [p for p in (detect_at, iap_at) if p >= 0]
        if not positions:
            if len(stream) > 8:
                del stream[:-8]
            break
        start = min(positions)
        if start:
            del stream[:start]
        if stream.startswith(DETECT):
            del stream[:len(DETECT)]
            items.append(("detect", DETECT))
            continue
        if len(stream) < 9:
            break
        packet_length = int.from_bytes(stream[2:4], "big")
        if packet_length < 9 or packet_length > 65535 or (sum(stream[:9]) & 0xFF):
            del stream[0]
            continue
        if len(stream) < packet_length:
            break
        packet = bytes(stream[:packet_length])
        if packet_length > 9 and ((sum(packet[9:-1]) + packet[-1]) & 0xFF):
            del stream[0]
            continue
        del stream[:packet_length]
        items.append(("iap", packet))
    return items


def describe_csm(data):
    if len(data) < 6 or data[:2] != b"\x40\x40":
        return
    length = int.from_bytes(data[2:4], "big")
    msg = int.from_bytes(data[4:6], "big")
    print(f"[{now()}] CSM message=0x{msg:04X}, declared_length={length}, buffered={len(data)}")
    if len(data) < length:
        return
    pos = 6
    while pos + 4 <= length:
        plen = int.from_bytes(data[pos:pos + 2], "big")
        pid = int.from_bytes(data[pos + 2:pos + 4], "big")
        if plen < 4 or pos + plen > length:
            break
        value = data[pos + 4:pos + plen]
        printable = value.rstrip(b"\x00")
        try:
            text = printable.decode("utf-8")
            if not text.isprintable():
                raise ValueError
            shown = repr(text)
        except (UnicodeDecodeError, ValueError):
            shown = value.hex(" ")
        print(f"  parameter 0x{pid:04X}, length={plen}: {shown}")
        pos += plen


def make_csm(message_id, params=()):
    body = bytearray()
    for parameter_id, value in params:
        body.extend((len(value) + 4).to_bytes(2, "big"))
        body.extend(parameter_id.to_bytes(2, "big"))
        body.extend(value)
    return b"\x40\x40" + (len(body) + 6).to_bytes(2, "big") + message_id.to_bytes(2, "big") + body


def parse_csm(data):
    length = int.from_bytes(data[2:4], "big")
    message_id = int.from_bytes(data[4:6], "big")
    params = []
    pos = 6
    while pos + 4 <= length:
        plen = int.from_bytes(data[pos:pos + 2], "big")
        pid = int.from_bytes(data[pos + 2:pos + 4], "big")
        if plen < 4 or pos + plen > length:
            break
        params.append((pid, bytes(data[pos + 4:pos + plen])))
        pos += plen
    return message_id, params


backend = libusb_package.get_libusb1_backend()
print("FLIR ONE iAP2 authenticated FRAME probe")
print("No persistent writes; authenticates iAP2, keeps config session alive, reads EP85.")

attempt = 0
while True:
    dev = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
    if dev is None:
        time.sleep(0.03)
        continue

    attempt += 1
    print(f"\n[{now()}] Connected (attempt {attempt})")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    capture_path = CAPTURE_DIR / f"identify-{stamp}.bin"
    detect_done = syn_done = identify_sent = False
    host_seq = 1
    peer_seq = 0
    control_stream = bytearray()
    config_stream = bytearray()
    transport_stream = bytearray()
    next_after_ack = None
    frame_started = False
    frame_bytes = 0
    frame_chunks = 0
    frame_stream = bytearray()
    live_frames = 0
    first_full_frame_logged = False
    last_frame_at = time.monotonic()
    frame_restarts = 0
    last_keepalive_at = time.monotonic()
    keepalive_pending = False
    keepalive_transfer_id = 1
    challenge = bytes(range(20))

    try:
        cfg = dev.get_active_configuration()
        intf = usb.util.find_descriptor(cfg, bInterfaceNumber=INTERFACE)
        if intf is None:
            raise RuntimeError("MI_00 not found")
        usb.util.claim_interface(dev, INTERFACE)
        usb.util.claim_interface(dev, 1)
        usb.util.claim_interface(dev, 2)

        with capture_path.open("ab") as capture:
            while True:
                if frame_started:
                    try:
                        frame = bytes(dev.read(0x85, 1048576, timeout=25))
                        if frame:
                            frame_chunks += 1
                            frame_bytes += len(frame)
                            frame_stream.extend(frame)
                            while True:
                                completed = pop_complete_ep85_frame(frame_stream)
                                if completed is None:
                                    break
                                record, header = completed
                                frame_size, thermal_size, jpeg_size, status_size = header
                                total = len(record)
                                if not first_full_frame_logged:
                                    info = inspect_ep85_frame(record)
                                    (CAPTURE_DIR / f"frame85-full-{stamp}.bin").write_bytes(record)
                                    signature = (
                                        f"found SOI={info['jpeg_soi']} EOI={info['jpeg_eoi']}"
                                        if info["jpeg_soi"] >= 0 and info["jpeg_eoi"] >= 0
                                        else "not-found"
                                    )
                                    print(
                                        f"[{now()}] FIRST FULL EP85 "
                                        f"HEADER28={info['header_hex']} "
                                        f"FrameSize={info['frame_size']} "
                                        f"ThermalSize={info['thermal_size']} "
                                        f"JpgSize={info['jpeg_size']} "
                                        f"StatusSize={info['status_size']} "
                                        f"Residual={info['residual']} "
                                        f"JPEG({info['jpeg_scan_scope']})={signature}",
                                        flush=True,
                                    )
                                    first_full_frame_logged = True
                                last_frame_at = time.monotonic()
                                published = publish_frame(record)
                                if published is None:
                                    continue
                                lo, hi, jpeg_size, status_size = published
                                live_frames += 1
                                frame_restarts = 0
                                print(
                                    f"[{now()}] LIVE frame={live_frames} bytes={total} "
                                    f"raw={lo}..{hi} visual={jpeg_size} status={status_size}",
                                    flush=True,
                                )
                    except usb.core.USBTimeoutError:
                        pass
                    except usb.core.USBError as exc:
                        # libusb/WinUSB sometimes reports an ordinary read
                        # timeout as WSAETIMEDOUT (10060), not USBTimeoutError.
                        # It only means EP85 has no complete frame yet.
                        if getattr(exc, "errno", None) != 10060:
                            raise
                    # WinUSB can leave an isochronous/bulk endpoint open but
                    # permanently silent.  A process-liveness check cannot see
                    # that failure, so recover based on completed-frame age.
                    if time.monotonic() - last_frame_at > 3.0:
                        frame_restarts += 1
                        if frame_restarts <= 2:
                            print(
                                f"[{now()}] RECOVERY frame stream stalled; "
                                f"restarting MI_02 ({frame_restarts}/2)",
                                flush=True,
                            )
                            dev.set_interface_altsetting(interface=2, alternate_setting=0)
                            if frame_restarts == 2:
                                dev.set_interface_altsetting(interface=1, alternate_setting=0)
                            time.sleep(0.05)
                            if frame_restarts == 2:
                                dev.set_interface_altsetting(interface=1, alternate_setting=1)
                            dev.set_interface_altsetting(interface=2, alternate_setting=1)
                            try:
                                dev.clear_halt(0x85)
                            except usb.core.USBError:
                                pass
                            frame_stream.clear()
                            last_frame_at = time.monotonic()
                        else:
                            print(
                                f"[{now()}] RECOVERY endpoint restart failed; "
                                "reopening USB session without a bus reset",
                                flush=True,
                            )
                            raise RuntimeError("frame stream stalled after automatic recovery")
                if (
                    frame_started
                    and not keepalive_pending
                    and time.monotonic() - last_keepalive_at >= 30.0
                ):
                    # The real app periodically talks on the Rosebud config
                    # session. Reasserting the already-enabled auto-FFC option
                    # is harmless and prevents the accessory session from
                    # becoming idle while EP85 continues streaming.
                    host_seq = (host_seq + 1) & 0xFF
                    rbp = rbp_config_packet("setOption", {"autoFFC": True})
                    ea_payload = keepalive_transfer_id.to_bytes(2, "big") + rbp
                    request = link_packet(0x40, host_seq, peer_seq, 2, ea_payload)
                    usb_write(dev, EP_OUT, request, timeout=500)
                    keepalive_transfer_id = (keepalive_transfer_id + 1) & 0xFFFF
                    keepalive_pending = True
                    last_keepalive_at = time.monotonic()
                    print(f"[{now()}] KEEPALIVE autoFFC=true sent", flush=True)
                try:
                    raw = bytes(dev.read(EP_IN, 65535, timeout=1 if frame_started else 100))
                except usb.core.USBTimeoutError:
                    continue
                except usb.core.USBError as exc:
                    if getattr(exc, "errno", None) == 10060:
                        continue
                    raise
                if not raw:
                    continue
                capture.write(raw)
                capture.flush()
                print(f"[{now()}] IN  ({len(raw):5d}): {raw[:192].hex(' ')}")

                transport_stream.extend(raw)
                transport_items = extract_transport_items(transport_stream)
                last_iap_item = max(
                    (
                        index for index, item in enumerate(transport_items)
                        if item[0] == "iap" and len(item[1]) > 10
                    ),
                    default=-1,
                )
                for item_index, (item_type, packet) in enumerate(transport_items):
                    if item_type == "detect":
                        if not detect_done:
                            usb_write(dev, EP_OUT, DETECT, timeout=500)
                            detect_done = True
                            print(f"[{now()}] OUT ({len(DETECT):5d}): {DETECT.hex(' ')} [DETECT echo]")
                        continue
                    control, seq, ack, session, payload = parse_link(packet)

                    # A USB reset does not necessarily restart usbiap2_poc.  If we
                    # attach to an already-running link, recover its sequence state
                    # from the first data packet instead of waiting forever for SYN.
                    if control & 0x40 and not syn_done:
                        syn_done = True
                        host_seq = ack
                        peer_seq = seq
                        print(
                            f"[{now()}] Reattached to active iAP2 link: "
                            f"host_seq={host_seq}, peer_seq={peer_seq}",
                            flush=True,
                        )

                    if control == 0x80 and not syn_done:
                        peer_seq = seq
                        syn_ack = link_packet(0xC0, host_seq, peer_seq, 0, payload)
                        usb_write(dev, EP_OUT, syn_ack, timeout=500)
                        syn_done = True
                        print(f"[{now()}] OUT ({len(syn_ack):5d}): {syn_ack.hex(' ')} [SYN-ACK]")
                        continue

                    if syn_done and control & 0x40:
                        if keepalive_pending and ack == host_seq:
                            keepalive_pending = False
                            print(f"[{now()}] KEEPALIVE acknowledged", flush=True)
                        if payload:
                            peer_seq = seq
                            # Link ACKs are cumulative.  WinUSB may return a
                            # backlog of many iAP packets in one read; ACKing
                            # every historical packet floods EP02 and causes
                            # the 10060 loop. ACK only the newest packet.
                            if item_index == last_iap_item:
                                ack_packet = link_packet(0x40, host_seq, peer_seq)
                                usb_write(dev, EP_OUT, ack_packet, timeout=500)
                                print(f"[{now()}] OUT ({len(ack_packet):5d}): {ack_packet.hex(' ')} [cumulative link ACK]")
                            if session == 1:
                                control_stream.extend(payload)
                                while len(control_stream) >= 6 and control_stream[:2] == b"\x40\x40":
                                    csm_length = int.from_bytes(control_stream[2:4], "big")
                                    if csm_length < 6 or len(control_stream) < csm_length:
                                        break
                                    complete_csm = bytes(control_stream[:csm_length])
                                    del control_stream[:csm_length]
                                    describe_csm(complete_csm)
                                    message_id, params = parse_csm(complete_csm)

                                    def send_csm(message, label):
                                        nonlocal_host_seq = (host_seq + 1) & 0xFF
                                        request = link_packet(0x40, nonlocal_host_seq, peer_seq, 1, message)
                                        usb_write(dev, EP_OUT, request, timeout=500)
                                        print(f"[{now()}] OUT ({len(request):5d}): {request.hex(' ')} [{label}]")
                                        return nonlocal_host_seq

                                    if message_id == 0x1D01:
                                        host_seq = send_csm(make_csm(0x1D02), "IdentificationAccepted 0x1D02")
                                        next_after_ack = (make_csm(0xAA00), "RequestAuthenticationCertificate 0xAA00")
                                    elif message_id == 0xAA01:
                                        certificate = next((v for pid, v in params if pid == 0), b"")
                                        cert_path = CAPTURE_DIR / f"mfi-certificate-{stamp}.der"
                                        cert_path.write_bytes(certificate)
                                        print(f"[{now()}] Saved MFi certificate: {cert_path} ({len(certificate)} bytes)")
                                        host_seq = send_csm(
                                            make_csm(0xAA02, [(0, challenge)]),
                                            "RequestAuthenticationChallengeResponse 0xAA02",
                                        )
                                    elif message_id == 0xAA03:
                                        response = next((v for pid, v in params if pid == 0), b"")
                                        response_path = CAPTURE_DIR / f"mfi-response-{stamp}.bin"
                                        response_path.write_bytes(response)
                                        print(f"[{now()}] Saved MFi challenge response: {response_path} ({len(response)} bytes)")
                                        host_seq = send_csm(make_csm(0xAA05), "AuthenticationSucceeded 0xAA05")
                                        # EA02 from this accessory asks iOS to launch com.flir.one.
                                        # Keep the known-good Rosebud config protocol on session 2.
                                        start_config = make_csm(
                                            0xEA00,
                                            [
                                                (0, b"\x00"),
                                                (1, b"\x00\x02"),
                                            ],
                                        )
                                        next_after_ack = (
                                            start_config,
                                            "StartExternalAccessoryProtocolSession config=0 session=2 (EA00)",
                                        )
                                    elif message_id == 0xEA00:
                                        protocol_id = next((v[0] for pid, v in params if pid == 0 and v), None)
                                        ea_session = next(
                                            (int.from_bytes(v, "big") for pid, v in params if pid == 1),
                                            None,
                                        )
                                        print(
                                            f"[{now()}] EA CONFIG SESSION STARTED: "
                                            f"protocol_id={protocol_id}, link_session={ea_session}"
                                        )
                            elif session == 2:
                                publish_status_message(payload)
                                config_stream.extend(payload)
                                config_path = CAPTURE_DIR / f"rosebud-config-{stamp}.bin"
                                config_path.write_bytes(config_stream)
                                try:
                                    display = payload.decode("utf-8")
                                    if not display.isprintable():
                                        raise ValueError
                                except (UnicodeDecodeError, ValueError):
                                    display = payload.hex(" ")
                                print(f"[{now()}] ROSEBUD CONFIG ({len(payload)} bytes): {display}")
                                if not frame_started:
                                    dev.set_interface_altsetting(interface=2, alternate_setting=0)
                                    dev.set_interface_altsetting(interface=1, alternate_setting=0)
                                    dev.set_interface_altsetting(interface=1, alternate_setting=1)
                                    dev.set_interface_altsetting(interface=2, alternate_setting=1)
                                    try:
                                        dev.clear_halt(0x85)
                                    except USBError:
                                        pass
                                    frame_started = True
                                    last_frame_at = time.monotonic()
                                    frame_restarts = 0
                                    print(
                                        f"[{now()}] Active config session recovered; "
                                        "MI_01/MI_02 alt 1 selected; polling EP85",
                                        flush=True,
                                    )
                        elif not identify_sent and ack == host_seq:
                            host_seq = (host_seq + 1) & 0xFF
                            request = link_packet(
                                0x40, host_seq, peer_seq, 1, START_IDENTIFICATION
                            )
                            usb_write(dev, EP_OUT, request, timeout=500)
                            identify_sent = True
                            print(
                                f"[{now()}] OUT ({len(request):5d}): {request.hex(' ')} "
                                "[StartIdentification 0x1D00]"
                            )
                        elif next_after_ack is not None and ack == host_seq:
                            message, label = next_after_ack
                            next_after_ack = None
                            host_seq = (host_seq + 1) & 0xFF
                            request = link_packet(0x40, host_seq, peer_seq, 1, message)
                            usb_write(dev, EP_OUT, request, timeout=500)
                            print(f"[{now()}] OUT ({len(request):5d}): {request.hex(' ')} [{label}]")
                            if "EA00" in label:
                                dev.set_interface_altsetting(interface=2, alternate_setting=0)
                                dev.set_interface_altsetting(interface=1, alternate_setting=0)
                                dev.set_interface_altsetting(interface=1, alternate_setting=1)
                                dev.set_interface_altsetting(interface=2, alternate_setting=1)
                                try:
                                    dev.clear_halt(0x85)
                                except USBError:
                                    pass
                                frame_started = True
                                last_frame_at = time.monotonic()
                                frame_restarts = 0
                                print(
                                    f"[{now()}] CONFIG SESSION ALIVE; MI_01/MI_02 alt 1 "
                                    "selected; polling EP85",
                                    flush=True,
                                )
    except (usb.core.USBError, RuntimeError, ValueError) as exc:
        print(f"[{now()}] Disconnected/error: {exc}")
    finally:
        try:
            usb.util.release_interface(dev, 2)
        except Exception:
            pass
        try:
            usb.util.release_interface(dev, 1)
        except Exception:
            pass
        try:
            usb.util.release_interface(dev, INTERFACE)
        except Exception:
            pass
        usb.util.dispose_resources(dev)
        time.sleep(0.03)
