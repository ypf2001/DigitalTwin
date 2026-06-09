$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Project = "D:\dw_plc\xiaweiji\xiaweiji.ap21"
$Source = "D:\dw_plc\xiaweiji\src\xiaweiji.scl"

$GroupInfo = (net localgroup "Siemens TIA Openness") -join "`n"
$CurrentUser = $env:USERNAME
if ($GroupInfo -notmatch [regex]::Escape($CurrentUser)) {
  Write-Error "Current user '$CurrentUser' is not in 'Siemens TIA Openness'. Run PowerShell as Administrator: net localgroup `"Siemens TIA Openness`" `"$CurrentUser`" /add, then sign out or restart."
}

python "$Root\examples\import_scl_to_project.py" `
  --project "$Project" `
  --source "$Source" `
  --source-name "xiaweiji" `
  --compile
