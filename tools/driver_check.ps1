$ErrorActionPreference = "SilentlyContinue"

$devices = Get-PnpDevice -PresentOnly | Where-Object {
    $_.InstanceId -match "VID_09CB&PID_1996"
}

if (-not $devices) {
    Write-Host "FLIR ONE was not found (VID 09CB, PID 1996)." -ForegroundColor Yellow
    Write-Host "Power the camera, verify the USB data wiring, and reconnect it."
    Write-Host "See docs\USER_GUIDE.md for the connection and Zadig guide."
    exit 0
}

Write-Host "FLIR ONE interface(s):" -ForegroundColor Green
foreach ($device in $devices) {
    $service = (Get-PnpDeviceProperty -InstanceId $device.InstanceId `
        -KeyName "DEVPKEY_Device_Service").Data
    Write-Host ("- {0}" -f $device.FriendlyName)
    Write-Host ("  {0}" -f $device.InstanceId)
    Write-Host ("  Status: {0}; service: {1}" -f $device.Status, $service)
}

$missing = $devices | Where-Object {
    $service = (Get-PnpDeviceProperty -InstanceId $_.InstanceId `
        -KeyName "DEVPKEY_Device_Service").Data
    $service -ne "WinUSB"
}

Write-Host ""
if ($missing) {
    Write-Host "At least one FLIR interface is not using WinUSB." -ForegroundColor Yellow
    Write-Host "Install WinUSB only on VID 09CB / PID 1996 interfaces MI_00, MI_01 and MI_02."
    Write-Host "Open https://zadig.akeo.ie/ and follow docs\USER_GUIDE.md."
    $answer = Read-Host "Open the official Zadig website now? [y/N]"
    if ($answer -match "^[Yy]") {
        Start-Process "https://zadig.akeo.ie/"
    }
} else {
    Write-Host "All detected FLIR interfaces use WinUSB." -ForegroundColor Green
}

