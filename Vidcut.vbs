' Opens Vidcut like a normal program: no console window. Double-click this file, or use the Vidcut shortcut.
Option Explicit
Dim sh, fso, here, py
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
py = here & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(py) Then
  MsgBox "Vidcut is not installed yet. Please double-click setup.bat first.", 48, "Vidcut"
  WScript.Quit 1
End If
sh.CurrentDirectory = here
' 0 = hidden window, False = do not wait for it to finish
sh.Run """" & py & """ -m server.desktop", 0, False
