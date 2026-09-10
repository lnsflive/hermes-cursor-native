param(
  [string]$Ref = $(if ($env:HCN_REF) { $env:HCN_REF } else { "main" })
)

$ErrorActionPreference = "Stop"
$Repo = if ($env:HCN_REPO) { $env:HCN_REPO } else { "https://github.com/lnsflive/hermes-cursor-native.git" }
$Spec = "git+$Repo@$Ref"
if ($Repo.StartsWith("file:") -or (Test-Path $Repo)) { $Spec = $Repo }

Write-Host "Hermes Cursor Native bootstrap ($Ref)"

$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($uv) {
  & $uv.Source tool install --force $Spec
  if ($LASTEXITCODE -ne 0) { throw "uv tool install failed" }
} else {
  $python = Get-Command py -ErrorAction SilentlyContinue
  if (-not $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
  if (-not $python) {
    throw "Python 3.11+ or uv is required. Hermes installations normally provide uv."
  }
  & $python.Source -m pip install --user --upgrade $Spec
  if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
}

$cli = Get-Command hermes-cursor-native -ErrorAction SilentlyContinue
if ($env:HCN_BOOTSTRAP_ONLY -eq "1") {
  Write-Host "Hermes Cursor Native CLI installed."
  exit 0
}
if ($cli) {
  & $cli.Source install
  exit $LASTEXITCODE
}
if ($uv) {
  & $uv.Source tool run hermes-cursor-native install
  exit $LASTEXITCODE
}

if (-not $python) {
  $python = Get-Command py -ErrorAction SilentlyContinue
  if (-not $python) { $python = Get-Command python -ErrorAction Stop }
}
& $python.Source -m hermes_cursor_native.cli install
exit $LASTEXITCODE
