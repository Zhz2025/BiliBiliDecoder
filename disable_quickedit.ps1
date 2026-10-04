# Disable QuickEdit for the CURRENT console window only.
#
# Why: in a classic conhost window, clicking/dragging inside the window while a
#      program is running pauses that program until you press Enter. Clearing the
#      QuickEdit flag prevents that freeze. Other terminals are not affected.
#
# Called automatically by run.bat / search_group.bat. Failure is harmless.
# NOTE: keep this file ASCII-only - Windows PowerShell 5.1 reads BOM-less .ps1
#       files as ANSI, which would corrupt non-ASCII text.

$sig = @'
[DllImport("kernel32.dll", SetLastError = true)]
public static extern IntPtr GetStdHandle(int nStdHandle);

[DllImport("kernel32.dll", SetLastError = true)]
public static extern bool GetConsoleMode(IntPtr hConsoleHandle, out uint lpMode);

[DllImport("kernel32.dll", SetLastError = true)]
public static extern bool SetConsoleMode(IntPtr hConsoleHandle, uint dwMode);
'@

try {
    $k = Add-Type -MemberDefinition $sig -Name Kernel32 -Namespace QuickEditFix -PassThru
    $h = $k::GetStdHandle(-11)   # STD_OUTPUT_HANDLE

    $mode = [uint32]0
    if (-not $k::GetConsoleMode($h, [ref]$mode)) {
        Write-Output '[QuickEdit] cannot read console mode (ignored)'
        exit 0
    }

    if (($mode -band 0x40) -eq 0) {
        Write-Output '[QuickEdit] already off'
        exit 0
    }

    # clear ENABLE_QUICK_EDIT_MODE(0x40), set ENABLE_EXTENDED_FLAGS(0x80)
    $newMode = ($mode -band (-bnot 0x40)) -bor 0x80
    if ($k::SetConsoleMode($h, $newMode)) {
        Write-Output '[QuickEdit] disabled - clicking this window will not pause the run'
    } else {
        Write-Output '[QuickEdit] not supported by this window type (harmless)'
    }
} catch {
    Write-Output '[QuickEdit] skipped (harmless)'
}
