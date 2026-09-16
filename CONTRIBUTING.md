# Contributing

Bug fixes, documentation improvements and reproducible protocol research are welcome.

## Visible-camera research

The highest-priority open issue is enabling the Gen 2 iOS unit's 640×480 visual
camera. Please include enough evidence for another person to repeat the result:

- exact camera model and Rosebud firmware version;
- Windows USB interface/endpoint descriptors;
- USBPcap/Wireshark traffic from a genuinely working visual stream;
- the startup order and exact payloads, with direction/interface/endpoint;
- frame-header values before and after enabling the stream;
- a small test program or patch where possible.

Do not submit guessed vendor-control values as confirmed commands. Clearly mark
untested hypotheses. Do not include proprietary SDK binaries, APKs, firmware,
private keys, authentication material, personal captures or other files you do
not have permission to redistribute.

## Development

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m py_compile outputs\flir_live_viewer.py work\flir_iap2_frame.py
```

Keep experimental USB probes separate from the normal launcher. The default
viewer must remain thermal-safe and must not write persistent camera settings.

