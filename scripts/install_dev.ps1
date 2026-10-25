$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # no progress bars
. (Join-Path $PSScriptRoot "_output.ps1")
trap { Fail "$_"; exit 1 }

Steps 2 "Installing the dev package"
$root = Split-Path $PSScriptRoot -Parent

$msix = Get-ChildItem (Join-Path $root "dist\msix\dev-*.msix") -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $msix) { Fatal "no dev package in dist\msix" "run [DEV] Build MSIX first" }

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { Fatal "no .venv at $python" "create it, the build tasks need it too" }
$identity = & $python -c "import sys; sys.path.insert(0, r'$root'); from src import APP_NAME, PACKAGE_ID; print(PACKAGE_ID); print(APP_NAME.replace(' ', '')); print(f'CN={APP_NAME} - Dev')"
if ($LASTEXITCODE -ne 0 -or @($identity).Count -lt 3) {
    Fatal "could not read the identity from pyproject.toml"
}
$name, $process, $publisher = $identity

$cert = Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.Subject -eq $publisher } |
    Sort-Object NotAfter -Descending | Select-Object -First 1
if (-not $cert) { Fatal "no dev certificate for $publisher" "run [DEV] Build MSIX first" }
if ($cert.NotAfter -le (Get-Date)) {
    Fatal "the dev certificate expired on $($cert.NotAfter.ToShortDateString())" "run [DEV] Build MSIX first"
}

Step "Trusting the dev certificate"
if (Get-ChildItem Cert:\LocalMachine\TrustedPeople | Where-Object { $_.Thumbprint -eq $cert.Thumbprint }) {
    Ok "$publisher already trusted"
} else {
    $cer = Join-Path ([IO.Path]::GetTempPath()) "$($cert.Thumbprint).cer"
    Export-Certificate -Cert $cert -FilePath $cer -Type CERT | Out-Null
    $import = "`$s = '$publisher'; `$t = '$($cert.Thumbprint)'; " +
        'Get-ChildItem Cert:\LocalMachine\TrustedPeople | ' +
        'Where-Object { $_.Subject -eq $s -and $_.Thumbprint -ne $t } | Remove-Item; ' +
        "Import-Certificate -FilePath '$cer' -CertStoreLocation Cert:\LocalMachine\TrustedPeople | Out-Null"
    try {
        $child = Start-Process powershell -Verb RunAs -Wait -PassThru -WindowStyle Hidden -ArgumentList @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $import)
    } catch {
        Fatal "the Windows prompt was refused, so the certificate is not trusted" `
            "run [DEV] Install again and accept the prompt"
    } finally {
        Remove-Item $cer -ErrorAction SilentlyContinue
    }
    if ($child.ExitCode -ne 0) { Fatal "could not trust $publisher" }
    Ok "$publisher trusted"
}

Step "Installing $($msix.Name)"
Get-Process -Name $process -ErrorAction SilentlyContinue | Stop-Process -Force
Get-AppxPackage -Name $name -Publisher $publisher | Remove-AppxPackage
Add-AppxPackage -Path $msix.FullName
Ok "$((Get-AppxPackage -Name $name -Publisher $publisher).Version) installed"
