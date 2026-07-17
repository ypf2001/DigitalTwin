param(
  [string]$PlcRepoPath = "D:\dw_plc\xiaweiji",
  [switch]$AllowMismatchedScl
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$DigitalTwinMirror = "D:\Digital Twin\plc\xiaweiji\src\xiaweiji.scl"
$Project = Join-Path $PlcRepoPath "xiaweiji.ap21"
$RepoSource = Join-Path $PlcRepoPath "src\xiaweiji.scl"

if (Test-Path -LiteralPath $DigitalTwinMirror) {
  # The Digital Twin source is canonical. The separate TIA project directory
  # only stores the .ap21 project; importing its stale src copy would silently
  # drop newer DB1 and batch-control fields.
  $Source = $DigitalTwinMirror
} elseif (Test-Path -LiteralPath $RepoSource) {
  Write-Warning "DigitalTwin SCL not found, falling back to PLC repo source: $RepoSource"
  $Source = $RepoSource
} else {
  throw "No xiaweiji.scl source found in either DigitalTwin or PLC repo path."
}

Write-Host "PLC repo path: $PlcRepoPath"
Write-Host "TIA project: $Project"
Write-Host "SCL source used: $Source"

if ((Test-Path -LiteralPath $RepoSource) -and (Test-Path -LiteralPath $DigitalTwinMirror)) {
  $RepoHash = (Get-FileHash -LiteralPath $RepoSource -Algorithm SHA256).Hash
  $MirrorHash = (Get-FileHash -LiteralPath $DigitalTwinMirror -Algorithm SHA256).Hash
  Write-Host "PLC repo SCL SHA256: $RepoHash"
  Write-Host "DigitalTwin mirror SCL SHA256: $MirrorHash"
  if ($RepoHash -ne $MirrorHash) {
    Write-Warning "SCL hash mismatch: importing the canonical DigitalTwin source, not the stale PLC repo copy."
  } else {
    Write-Host "SCL hash check passed: files are identical."
  }
}

$GroupInfo = (net localgroup "Siemens TIA Openness") -join "`n"
$CurrentUser = $env:USERNAME
if ($GroupInfo -notmatch [regex]::Escape($CurrentUser)) {
  Write-Error "Current user '$CurrentUser' is not in 'Siemens TIA Openness'. Run PowerShell as Administrator: net localgroup `"Siemens TIA Openness`" `"$CurrentUser`" /add, then sign out or restart."
}

python "$Root\examples\import_scl_to_project.py" `
  --project "$Project" `
  --source "$Source" `
  --source-name "xiaweiji"
if ($LASTEXITCODE -ne 0) {
  throw "SCL import failed with exit code $LASTEXITCODE"
}

$ModeSelectorLad = Join-Path $Root "generated_lad\FC_ModeSelector_LAD.xml"
if (-not (Test-Path -LiteralPath $ModeSelectorLad)) {
  throw "LAD mode selector XML not found: $ModeSelectorLad"
}
Write-Host "Importing LAD mode selector: $ModeSelectorLad"
python "$Root\examples\import_lad_xml.py" `
  --project "$Project" `
  --plc "PLC_1" `
  --xml "$ModeSelectorLad"
if ($LASTEXITCODE -ne 0) {
  throw "LAD mode selector import failed with exit code $LASTEXITCODE"
}

$ModeInterlockLad = Join-Path $Root "lad_templates\FC_ModeInterlock_LAD.xml"
if (Test-Path -LiteralPath $ModeInterlockLad) {
  Write-Host "Importing LAD mode interlock: $ModeInterlockLad"
  python "$Root\examples\import_lad_xml.py" `
    --project "$Project" `
    --plc "PLC_1" `
    --xml "$ModeInterlockLad" `
    --compile
  if ($LASTEXITCODE -ne 0) {
    throw "PLC compile failed with exit code $LASTEXITCODE"
  }
} else {
  Write-Warning "LAD mode interlock XML not found: $ModeInterlockLad"
  python "$Root\examples\import_scl_to_project.py" `
    --project "$Project" `
    --source "$Source" `
    --source-name "xiaweiji" `
    --compile `
    --go-online-after
  if ($LASTEXITCODE -ne 0) {
    throw "PLC compile failed with exit code $LASTEXITCODE"
  }
}
