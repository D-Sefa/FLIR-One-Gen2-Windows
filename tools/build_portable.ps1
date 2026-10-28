param([string]$VendorPath,[string]$Version='0.4.0')
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
if (!$VendorPath) { throw 'Provide -VendorPath containing official zadig-2.9.exe and libwdi-1.5.1-source.zip' }
$VendorPath = (Resolve-Path $VendorPath).Path
foreach($required in @('zadig-2.9.exe','libwdi-1.5.1-source.zip','COPYING','COPYING-LGPL','libusb-COPYING','libusb-1.0.30.tar.bz2','libusb-package-1.0.30.0-source.zip')) {
    if(!(Test-Path -LiteralPath (Join-Path $VendorPath $required))){throw "Missing vendor file: $required"}
}
Set-Location $repo
$python = Join-Path $repo '.venv/Scripts/python.exe'
function Check-Exit { if ($LASTEXITCODE -ne 0) { throw "Command failed with exit $LASTEXITCODE" } }
& $python -m unittest discover -s tests -v
Check-Exit
& $python -m PyInstaller --noconfirm --clean --onedir --contents-directory '_internal' --name FLIR-One-Gen2 --paths work --paths outputs --hidden-import flir_live_viewer --hidden-import flir_iap2_frame --add-data "$repo/outputs/flir_live_viewer.py;outputs" --add-data "$repo/work/flir_iap2_frame.py;work" --add-data "$repo/work/flir_display.py;work" --add-data "$repo/work/flir_gallery.py;work" --add-data "$repo/work/flir_playback.py;work" --distpath portable-dist --workpath portable-build --specpath portable-build tools/portable_entry.py
Check-Exit
$dest = Join-Path $repo 'portable-dist/FLIR-One-Gen2'
New-Item -ItemType Directory -Force -Path "$dest/drivers", "$dest/licenses", "$dest/licenses/sources" | Out-Null
Copy-Item -LiteralPath "$VendorPath/zadig-2.9.exe", "$VendorPath/libwdi-1.5.1-source.zip" -Destination "$dest/drivers"
Copy-Item -LiteralPath docs/PORTABLE_README.md -Destination "$dest/README.md"
Copy-Item -LiteralPath LICENSE -Destination "$dest/licenses/FLIR-project-MIT.txt"
Copy-Item -LiteralPath "$VendorPath/COPYING", "$VendorPath/COPYING-LGPL" -Destination "$dest/licenses"
Copy-Item -LiteralPath docs/PORTABLE_THIRD_PARTY.md -Destination "$dest/licenses/THIRD_PARTY.md"
Copy-Item -LiteralPath "$VendorPath/libusb-COPYING" -Destination "$dest/licenses/libusb-LGPL-2.1.txt"
Copy-Item -LiteralPath "$VendorPath/libusb-1.0.30.tar.bz2", "$VendorPath/libusb-package-1.0.30.0-source.zip" -Destination "$dest/licenses/sources"
# Preserve installed package license files, including Python/Tcl/Tk and libusb.
Get-ChildItem '.venv/Lib/site-packages' -Directory -Filter '*.dist-info' | ForEach-Object {
    $licenseFiles = Get-ChildItem $_.FullName -Recurse -File | Where-Object { $_.Name -match 'LICENSE|COPYING|NOTICE' }
    if ($licenseFiles) {
        $licenseDest = Join-Path "$dest/licenses" $_.Name
        New-Item -ItemType Directory -Force $licenseDest | Out-Null
        foreach ($item in $licenseFiles) { Copy-Item -LiteralPath $item.FullName -Destination $licenseDest }
    }
}
$runtime = & $python -c 'import sys; print(sys.base_prefix)'
Copy-Item -LiteralPath "$runtime/LICENSE.txt" -Destination "$dest/licenses/Python-LICENSE.txt"
Get-ChildItem "$runtime/tcl" -Recurse -File -Filter 'license.terms' | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination "$dest/licenses/$($_.Directory.Name)-license.terms"
}
& "$dest/FLIR-One-Gen2.exe" --self-test
Check-Exit
& "$dest/FLIR-One-Gen2.exe" -u work/flir_iap2_frame.py --self-test
Check-Exit
& "$dest/FLIR-One-Gen2.exe" --smoke-test
Check-Exit
# Remove only smoke-generated state inside this generated distribution. Never
# apply these paths to the source application's real outputs/recordings.
foreach ($relative in @('Data/outputs/FLIR_DVR','Data/outputs/FLIR Kayitlari','Data/outputs/flir-viewer-settings.json','Data/outputs/flir-storage-settings.json')) {
    $generated = [IO.Path]::GetFullPath((Join-Path $dest $relative))
    if (!$generated.StartsWith([IO.Path]::GetFullPath($dest) + [IO.Path]::DirectorySeparatorChar)) { throw 'Unsafe staging cleanup path' }
    if (Test-Path -LiteralPath $generated) { Remove-Item -LiteralPath $generated -Recurse -Force }
}
$archive=Join-Path $repo "portable-dist/FLIR-One-Gen2-Windows-Portable-v$Version.zip"
Compress-Archive -LiteralPath $dest -DestinationPath $archive -Force
Get-FileHash -LiteralPath $archive -Algorithm SHA256
