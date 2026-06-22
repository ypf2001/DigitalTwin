param(
  [string]$PlcRepoPath = "D:\dw_plc\xiaweiji",
  [switch]$AllowMismatchedScl
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$DigitalTwinMirror = "D:\Digital Twin\plc\xiaweiji\src\xiaweiji.scl"
$Project = Join-Path $PlcRepoPath "xiaweiji.ap21"
$RepoSource = Join-Path $PlcRepoPath "src\xiaweiji.scl"

if (Test-Path -LiteralPath $RepoSource) {
  $Source = $RepoSource
} else {
  Write-Warning "PLC repo SCL not found, falling back to DigitalTwin mirror: $DigitalTwinMirror"
  $Project = "D:\dw_plc\xiaweiji\xiaweiji.ap21"
  $Source = $DigitalTwinMirror
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
    if (-not $AllowMismatchedScl) {
      throw "SCL hash mismatch. Sync the two xiaweiji.scl files or pass -AllowMismatchedScl explicitly."
    }
    Write-Warning "SCL hash mismatch allowed by -AllowMismatchedScl."
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
  --source-name "xiaweiji" `
  --compile `
  --go-online-after
