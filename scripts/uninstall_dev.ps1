$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # no progress bars
. (Join-Path $PSScriptRoot "_output.ps1")
trap { Fail "$_"; exit 1 }

Steps 2 "Uninstalling the dev package"
$root = Split-Path $PSScriptRoot -Parent

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { Fatal "no .venv at $python" "create it, the build tasks need it too" }
$identity = & $python -c "import sys; sys.path.insert(0, r'$root'); from src import APP_NAME, PACKAGE_ID; print(PACKAGE_ID); print(f'CN={APP_NAME} - Dev')"
if ($LASTEXITCODE -ne 0 -or @($identity).Count -lt 2) {
    Fatal "could not read the identity from pyproject.toml"
}
$name, $publisher = $identity

Step "Removing the app"
$pkg = Get-AppxPackage -Name $name -Publisher $publisher
if ($pkg) {
    $pkg | Remove-AppxPackage
    Ok "$($pkg.Version) removed"
} else {
    Ok "no dev package installed"
}

Step "Removing the dev certificates"
$mine = @(Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.Subject -eq $publisher })
foreach ($cert in $mine) {
    # -DeleteKey only works with -Path, not piped
    if ($cert.HasPrivateKey) { Remove-Item -Path $cert.PSPath -DeleteKey } else { Remove-Item -Path $cert.PSPath }
}
$trusted = @(Get-ChildItem Cert:\LocalMachine\TrustedPeople | Where-Object { $_.Subject -eq $publisher })
if ($trusted) {
    $remove = "`$s = '$publisher'; " +
        'Get-ChildItem Cert:\LocalMachine\TrustedPeople | Where-Object { $_.Subject -eq $s } | Remove-Item'
    try {
        $child = Start-Process powershell -Verb RunAs -Wait -PassThru -WindowStyle Hidden -ArgumentList @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $remove)
    } catch {
        Fatal "the Windows prompt was refused, so the trusted copies are still there" `
            "run [DEV] Uninstall again and accept the prompt"
    }
    if ($child.ExitCode -ne 0) { Fatal "could not remove the trusted copies" }
}
$count = $mine.Count + $trusted.Count
if ($count -eq 0) {
    Ok "no dev certificate"
} elseif ($count -eq 1) {
    Ok "1 dev certificate removed"
} else {
    Ok "$count dev certificates removed"
}
