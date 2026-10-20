$ErrorActionPreference = "Stop"
$dir = $PSScriptRoot
$target = Join-Path $dir "start.bat"
$icon = Join-Path $dir "katya.ico"
$work = $dir

$ws = New-Object -ComObject WScript.Shell
$destinations = @(
  (Join-Path ([Environment]::GetFolderPath("Desktop")) "Katya 2.10.lnk"),
  (Join-Path $dir "Katya 2.10.lnk")
)
foreach ($p in $destinations) {
  $sc = $ws.CreateShortcut($p)
  $sc.TargetPath = $target
  $sc.Arguments = ""
  $sc.WorkingDirectory = $work
  $sc.IconLocation = "$icon,0"
  $sc.Description = "Katya 2.10 - Hyper-Drive"
  $sc.Save()
  Write-Host "Created: $p"
}
