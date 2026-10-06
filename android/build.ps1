param([string]$Toolchain=(Join-Path $PSScriptRoot '../../android-toolchain'))
$ErrorActionPreference='Stop'
$Toolchain=(Resolve-Path $Toolchain).Path
$jdk=Join-Path $Toolchain 'jdk/jdk-17.0.20.1+1/bin'
$tools=Join-Path $Toolchain 'build-tools/android-15'
$platform=Join-Path $Toolchain 'platform/android-35/android.jar'
$build=Join-Path $PSScriptRoot 'build'
New-Item -ItemType Directory -Force -Path "$build/classes","$build/dex","$build/tests" | Out-Null
function Check-Exit { if($LASTEXITCODE -ne 0){ throw "Build command failed: exit $LASTEXITCODE" } }
$core=@('Protocol','FrameParser','IapSession','Thermal','RawArchive','RawRecorder','Generation') | ForEach-Object { Join-Path $PSScriptRoot "src/com/dsefa/flir/$_.java" }
$testSources=Get-ChildItem "$PSScriptRoot/tests" -Filter '*.java' | Select-Object -ExpandProperty FullName
& "$jdk/javac.exe" -encoding UTF-8 -d "$build/tests" @core @testSources
Check-Exit
foreach($test in @('CoreTest','PacketRedTest','ArchiveTest','LifecycleTest','RecorderTest')) { & "$jdk/java.exe" -cp "$build/tests" "com.dsefa.flir.$test"; Check-Exit }
$sources=Get-ChildItem "$PSScriptRoot/src" -Filter '*.java' -Recurse | Select-Object -ExpandProperty FullName
& "$jdk/javac.exe" -encoding UTF-8 --release 8 -cp $platform -d "$build/classes" @sources
Check-Exit
$classes=Get-ChildItem "$build/classes" -Filter '*.class' -Recurse | Select-Object -ExpandProperty FullName
& "$jdk/java.exe" -cp "$tools/lib/d8.jar" com.android.tools.r8.D8 --min-api 26 --lib $platform --output "$build/dex" @classes
Check-Exit
& "$tools/aapt2.exe" compile --dir "$PSScriptRoot/res" -o "$build/resources.zip"
Check-Exit
& "$tools/aapt2.exe" link -I $platform --manifest "$PSScriptRoot/AndroidManifest.xml" -R "$build/resources.zip" -o "$build/unsigned.apk"
Check-Exit
& "$jdk/jar.exe" uf "$build/unsigned.apk" -C "$build/dex" classes.dex
Check-Exit
& "$tools/zipalign.exe" -f -p 4 "$build/unsigned.apk" "$build/aligned.apk"
Check-Exit
# Local preview key is outside the source tree. Do not redistribute it.
$keyDir=Join-Path $Toolchain 'private-signing'
New-Item -ItemType Directory -Force -Path $keyDir | Out-Null
$keyFile=Join-Path $keyDir 'flir-android.jks'
$passwordFile=Join-Path $keyDir 'password.txt'
if(!(Test-Path -LiteralPath $keyFile)){
    $password=[Guid]::NewGuid().ToString('N')+[Guid]::NewGuid().ToString('N')
    # Generated signing credential, not a source/configuration edit.
    [IO.File]::WriteAllText($passwordFile,$password,[Text.Encoding]::ASCII)
    & "$jdk/keytool.exe" -genkeypair -keystore $keyFile -storepass $password -keypass $password -alias flir-android -keyalg RSA -keysize 3072 -validity 10000 -dname 'CN=FLIR Gen2 Android Preview, OU=Independent Development, O=D-Sefa'
    Check-Exit
}
$out=Join-Path $PSScriptRoot '../outputs/FLIR-Gen2-Android-preview.apk'
& "$jdk/java.exe" -jar "$tools/lib/apksigner.jar" sign --ks $keyFile --ks-key-alias flir-android --ks-pass "file:$passwordFile" --out $out "$build/aligned.apk"
Check-Exit
& "$jdk/java.exe" -jar "$tools/lib/apksigner.jar" verify --verbose $out
Check-Exit
& "$tools/aapt2.exe" dump badging $out
Check-Exit
Get-FileHash -LiteralPath $out -Algorithm SHA256
