# Creates the Vidcut shortcuts (Desktop and Start menu). Run by setup.bat; safe to run again.
$root = Split-Path -Parent $PSScriptRoot
$shell = New-Object -ComObject WScript.Shell
$targets = @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))
foreach ($dir in $targets) {
  if (-not $dir -or -not (Test-Path $dir)) { continue }
  $lnk = $shell.CreateShortcut((Join-Path $dir "Vidcut.lnk"))
  $lnk.TargetPath = "wscript.exe"
  $lnk.Arguments = '"' + (Join-Path $root "Vidcut.vbs") + '"'
  $lnk.WorkingDirectory = $root
  $lnk.IconLocation = (Join-Path $root "assets\vidcut.ico")
  $lnk.Description = "Vidcut video cutter"
  $lnk.Save()
}
