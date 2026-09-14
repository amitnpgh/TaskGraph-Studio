Option Explicit
Dim shell, fs, folder, candidates, root, subfolder, candidate, chosen, result, entry, registryKey
Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
Set candidates = CreateObject("Scripting.Dictionary")
folder = fs.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = folder
If Not fs.FileExists(folder & "\launch_taskgraph.py") Or Not fs.FileExists(folder & "\desktop.py") Then
    MsgBox "Extract the complete Taskgraph ZIP, then open this launcher from the extracted folder. Required files are missing.", 48, "Taskgraph Studio"
    WScript.Quit 1
End If
' Prefer regular installations. Check Python version and Tkinter before launching.
For Each entry In Array("%LOCALAPPDATA%\Programs\Python", "%ProgramFiles%", "%ProgramFiles(x86)%")
    root = shell.ExpandEnvironmentStrings(entry)
    If fs.FolderExists(root) Then
        For Each subfolder In fs.GetFolder(root).SubFolders
            If LCase(Left(subfolder.Name, 6)) = "python" Then AddCandidate subfolder.Path & "\python.exe"
        Next
    End If
Next
For Each registryKey In Array("HKCU\Software\Python\PythonCore\", "HKLM\Software\Python\PythonCore\", "HKLM\Software\WOW6432Node\Python\PythonCore\")
    For Each entry In Array("3.15", "3.14", "3.13", "3.12", "3.11")
        On Error Resume Next
        candidate = ""
        candidate = shell.RegRead(registryKey & entry & "\InstallPath\")
        On Error GoTo 0
        If candidate <> "" Then AddCandidate fs.BuildPath(candidate, "python.exe")
    Next
Next
For Each entry In Split(shell.ExpandEnvironmentStrings("%PATH%"), ";")
    entry = Replace(Trim(entry), Chr(34), "")
    If entry <> "" And InStr(LCase(entry), "windowsapps") = 0 Then AddCandidate fs.BuildPath(entry, "python.exe")
Next
AddCandidate shell.ExpandEnvironmentStrings("%USERPROFILE%") & "\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
chosen = ""
For Each candidate In candidates.Keys
    On Error Resume Next
    Err.Clear
    result = shell.Run(Quote(candidate) & " " & Quote(folder & "\launch_taskgraph.py") & " --check-ui", 0, True)
    If Err.Number = 0 And result = 0 Then chosen = candidate
    On Error GoTo 0
    If chosen <> "" Then Exit For
Next
If chosen = "" Then
    MsgBox "No working Python 3.11+ installation with Tkinter was found." & vbCrLf & vbCrLf & "Install or repair Python with the Tcl/Tk and IDLE option enabled, then reopen Taskgraph." & vbCrLf & vbCrLf & "Startup check details, if available: " & folder & "\startup-error.txt" & vbCrLf & "Fallback log: taskgraph-startup-error.txt in your temporary folder.", 48, "Taskgraph Studio"
    WScript.Quit 1
End If
candidate = fs.BuildPath(fs.GetParentFolderName(chosen), "pythonw.exe")
If fs.FileExists(candidate) Then chosen = candidate
On Error Resume Next
Err.Clear
shell.Run Quote(chosen) & " " & Quote(folder & "\launch_taskgraph.py"), 0, False
If Err.Number <> 0 Then MsgBox "Windows could not launch Taskgraph: " & Err.Description, 16, "Taskgraph Studio"
On Error GoTo 0

Sub AddCandidate(path)
    If fs.FileExists(path) Then
        If Not candidates.Exists(LCase(path)) Then candidates.Add LCase(path), True
    End If
End Sub

Function Quote(value)
    Quote = Chr(34) & value & Chr(34)
End Function
