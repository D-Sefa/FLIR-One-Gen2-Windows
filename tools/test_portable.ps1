param([string]$Archive)
$ErrorActionPreference = 'Stop'
if (!$Archive) { throw 'Provide -Archive with the portable ZIP' }
$check = Join-Path ([IO.Path]::GetTempPath()) ('flir-portable-check-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $check | Out-Null
Expand-Archive -LiteralPath $Archive -DestinationPath $check
$bundle = Join-Path $check 'FLIR-One-Gen2'
$exe = Join-Path $bundle 'FLIR-One-Gen2.exe'
foreach($required in @('drivers/zadig-2.9.exe','drivers/libwdi-1.5.1-source.zip','licenses/libusb-LGPL-2.1.txt','licenses/sources/libusb-1.0.30.tar.bz2','licenses/sources/libusb-package-1.0.30.0-source.zip')) {
    if(!(Test-Path -LiteralPath (Join-Path $bundle $required))){throw "Distribution missing required third-party artifact: $required"}
}
$savedPath = $env:PATH
$savedHome = $env:PYTHONHOME
$savedPythonPath = $env:PYTHONPATH
$proc = $null
try {
    $env:PATH = "$env:SystemRoot/System32"
    $env:PYTHONHOME = $null
    $env:PYTHONPATH = $null
    & $exe --self-test
    if ($LASTEXITCODE -ne 0) { throw 'Relocated runtime self-test failed' }
    & $exe -u work/flir_iap2_frame.py --self-test
    if ($LASTEXITCODE -ne 0) { throw 'Capture dispatch self-test failed' }
    & $exe --smoke-test
    if ($LASTEXITCODE -ne 0) { throw 'Relocated Tk smoke failed' }
    $proc = Start-Process -FilePath $exe -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 4
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $($proc.Id)")
    $log = Join-Path $bundle 'Data/outputs/flir-capture.log'
    if (!$children.Count -or !(Test-Path -LiteralPath $log)) { throw 'Normal GUI failed to start capture/log pipe' }
    $logText = Get-Content -LiteralPath $log -Raw
    if (!$logText -or $logText.Contains('Traceback')) { throw "Capture pipe error: $logText" }
    if (Test-Path -LiteralPath (Join-Path $bundle 'portable-error.log')) { throw 'Normal startup produced an error log' }
    'PASS normal GUI startup and capture subprocess stdout pipe'
    $null = $proc.CloseMainWindow()
    if (!$proc.WaitForExit(5000)) {
        foreach ($child in $children) { Stop-Process -Id $child.ProcessId -ErrorAction SilentlyContinue }
        Stop-Process -Id $proc.Id -ErrorAction SilentlyContinue
    }
    $proc = $null
    # In this disposable extracted copy, force a worker startup failure. It must
    # exit and print a traceback, never open a hidden modal GUI dialog.
    Move-Item -LiteralPath (Join-Path $bundle '_internal/work/flir_iap2_frame.py') -Destination (Join-Path $bundle '_internal/work/capture-disabled.py')
    $worker = Start-Process -FilePath $exe -ArgumentList '-u work/flir_iap2_frame.py' -WindowStyle Hidden -PassThru -RedirectStandardError (Join-Path $check 'worker-error.txt') -RedirectStandardOutput (Join-Path $check 'worker-output.txt')
    if (!$worker.WaitForExit(5000)) { Stop-Process -Id $worker.Id; throw 'Worker error opened a blocking dialog' }
    $workerError = Get-Content -LiteralPath (Join-Path $check 'worker-error.txt') -Raw
    if ($worker.ExitCode -eq 0 -or !$workerError.Contains('Traceback') -or !$workerError.Contains('flir_iap2_frame.py')) { throw 'Worker failure was not reported through stderr' }
    'PASS failed worker exits with traceback instead of a modal dialog'
    "Verified extracted package at $bundle (retained for inspection)"
} finally {
    if ($proc -and !$proc.HasExited) {
        Get-CimInstance Win32_Process -Filter "ParentProcessId = $($proc.Id)" | ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
        Stop-Process -Id $proc.Id -ErrorAction SilentlyContinue
    }
    $env:PATH = $savedPath
    $env:PYTHONHOME = $savedHome
    $env:PYTHONPATH = $savedPythonPath
}
