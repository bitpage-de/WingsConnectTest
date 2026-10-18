<#
.SYNOPSIS
    Bereitet den Laptop für die Wings-Connect-Messung vor – oder setzt alles zurück (-Restore).

.DESCRIPTION
    Ziel: Die Messung darf während des Flugs nicht einschlafen, und nichts darf im
    Hintergrund die knappe Satellitenbandbreite verbrauchen.

    Schritte (umkehrbar, Ausgangszustand wird in prep_backup_state.json gesichert):
      1. Energie: Kopie des aktiven Schemas als "WingsConnect" anlegen und aktivieren.
         Darin: Standby/Ruhezustand = nie, Zuklappen = nichts tun,
         WLAN-Energiesparen = aus (Netz + Akku), Bildschirm aus nach 15 Min.
      2. WLAN-Adapter: "Computer darf Gerät ausschalten" deaktivieren.
         Best effort – auf diesem Laptop meldet der Treiber einen Gerätefehler.
         Wird NICHT zurückgesetzt (ist auch dauerhaft sinnvoll).
      3. Windows Update für 7 Tage pausieren, Dienste wuauserv/UsoSvc/DoSvc stoppen.
      4. Übermittlungsoptimierung: kein Peer-to-Peer-Upload (DODownloadMode = 0).
      5. Microsoft Store: automatische App-Updates aus.
      6. Cloud-Sync und Hintergrund-Apps beenden (Dropbox, OneDrive, Steam, Spotify ...).
         Bei -Restore werden Dropbox und OneDrive wieder gestartet.
      7. Windows-Zeitdienst starten und Uhr synchronisieren (saubere Zeitstempel).

    Administratorrechte werden per UAC-Dialog selbst angefordert. Die Ausgabe des
    erhöhten Prozesses landet in prep_lastrun.log und wird danach angezeigt.

.EXAMPLE
    .\prepare_laptop.ps1            # vorbereiten (heute, vor dem Flug)
    .\prepare_laptop.ps1 -Restore   # zurücksetzen (nach dem Flug)
#>
[CmdletBinding()]
param(
    [switch]$Restore,
    [string]$LogFile      # intern: wird beim Selbst-Elevieren gesetzt
)

$ErrorActionPreference = 'Continue'
$ScriptPath = $MyInvocation.MyCommand.Path
$ScriptDir  = Split-Path -Parent $ScriptPath
$BackupFile = Join-Path $ScriptDir 'prep_backup_state.json'
$GuidRegex  = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'

# GUIDs der Energieeinstellung "Drahtlosadaptereinstellungen > Energiesparmodus"
$WifiPowerSub = '19cbb8fa-5279-450e-9fac-8a3d5fedd0c1'
$WifiPowerSet = '12bbebe6-58d6-4636-95bb-3217ef867c1a'

$WuPath    = 'HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings'
$WuNames   = @('PauseFeatureUpdatesStartTime', 'PauseFeatureUpdatesEndTime',
               'PauseQualityUpdatesStartTime', 'PauseQualityUpdatesEndTime',
               'PauseUpdatesStartTime', 'PauseUpdatesExpiryTime')
$DoPath    = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\DeliveryOptimization'
$StorePath = 'HKLM:\SOFTWARE\Policies\Microsoft\WindowsStore'

$AppNames = @('Dropbox', 'OneDrive', 'GoogleDriveFS', 'Steam', 'Spotify', 'Discord',
              'Teams', 'ms-teams', 'Slack', 'EpicGamesLauncher', 'Backblaze', 'bztransmit',
              'Nextcloud', 'iCloudDrive', 'iCloudServices', 'iCloudPhotos',
              'CCXProcess', 'Creative Cloud', 'AdobeUpdateService')

# ------------------------------------------------------------------ Hilfsfunktionen
function Log {
    param([string]$Msg, [string]$Color = 'Gray')
    Write-Host $Msg -ForegroundColor $Color
    if ($LogFile) { Add-Content -Path $LogFile -Value $Msg -Encoding UTF8 }
}

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal $id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-RegValue($Path, $Name) {
    try { (Get-ItemProperty -Path $Path -Name $Name -ErrorAction Stop).$Name } catch { $null }
}

function Set-RegValue($Path, $Name, $Value, $Type) {
    if (-not (Test-Path $Path)) { New-Item -Path $Path -Force | Out-Null }
    New-ItemProperty -Path $Path -Name $Name -Value $Value -PropertyType $Type -Force | Out-Null
}

function Restore-RegValue($Path, $Name, $Old, $Type) {
    if ($null -eq $Old) {
        if ($null -ne (Get-RegValue $Path $Name)) { Remove-ItemProperty -Path $Path -Name $Name -Force }
    } else {
        Set-RegValue $Path $Name $Old $Type
    }
}

function Get-ActiveSchemeGuid {
    [regex]::Match(((powercfg /getactivescheme) -join ' '), $GuidRegex).Value
}

function Get-PowerIndex($Sub, $Setting) {
    # liefert "AC=0x.. DC=0x.." der aktuellen Werte
    $o = (powercfg /query SCHEME_CURRENT $Sub $Setting) -join "`n"
    $ac = [regex]::Match($o, '(?:AC Power Setting Index|Wechselstromeinstellung):\s*(0x[0-9a-f]+)').Groups[1].Value
    $dc = [regex]::Match($o, '(?:DC Power Setting Index|Gleichstromeinstellung):\s*(0x[0-9a-f]+)').Groups[1].Value
    "AC=$ac DC=$dc"
}

function Show-Status {
    Log ""
    Log "---- Aktueller Zustand ----" 'Cyan'
    Log ("Energieschema:        " + ((powercfg /getactivescheme) -join ' '))
    Log ("Standby (s):          " + (Get-PowerIndex SUB_SLEEP   STANDBYIDLE))
    Log ("Ruhezustand (s):      " + (Get-PowerIndex SUB_SLEEP   HIBERNATEIDLE))
    Log ("Zuklappen (0=nichts): " + (Get-PowerIndex SUB_BUTTONS LIDACTION))
    Log ("WLAN-Sparmodus (0=max):" + (Get-PowerIndex $WifiPowerSub $WifiPowerSet))
    Log ("Windows Update Pause: bis " + (Get-RegValue $WuPath 'PauseUpdatesExpiryTime'))
    foreach ($svc in 'wuauserv', 'UsoSvc', 'DoSvc', 'w32time') {
        try { Log ("Dienst {0,-9} {1}" -f $svc, (Get-Service $svc -ErrorAction Stop).Status) } catch {}
    }
    $running = Get-Process | Where-Object { $AppNames -contains $_.ProcessName } |
               Select-Object -ExpandProperty ProcessName -Unique
    if ($running) { Log ("Hintergrund-Apps:     " + ($running -join ', ')) 'Yellow' }
    else          { Log  "Hintergrund-Apps:     keine der überwachten läuft" 'Green' }
    $bat = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($bat) { Log ("Akku:                 {0}% (Status {1})" -f $bat.EstimatedChargeRemaining, $bat.BatteryStatus) }
}

# ------------------------------------------------------------------ Selbst-Elevierung
if (-not (Test-Admin)) {
    $log = Join-Path $ScriptDir 'prep_lastrun.log'
    if (Test-Path $log) { Remove-Item $log -Force }
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$ScriptPath`"", '-LogFile', "`"$log`"")
    if ($Restore) { $argList += '-Restore' }
    Write-Host "Fordere Administratorrechte an – bitte UAC-Dialog bestätigen ..." -ForegroundColor Cyan
    try {
        $p = Start-Process powershell.exe -Verb RunAs -ArgumentList $argList -Wait -PassThru -ErrorAction Stop
    } catch {
        Write-Warning "UAC abgelehnt oder fehlgeschlagen: $($_.Exception.Message)"
        exit 1
    }
    if (Test-Path $log) { Get-Content $log } else { Write-Warning "Kein Log geschrieben." }
    exit $p.ExitCode
}

# ================================================================== RESTORE
if ($Restore) {
    Log "=== Wings Connect: Laptop zurücksetzen ===" 'Cyan'
    if (-not (Test-Path $BackupFile)) {
        Log "Kein Backup ($BackupFile) gefunden – nichts zurückzusetzen." 'Yellow'
        Show-Status
        exit 1
    }
    $s = Get-Content $BackupFile -Raw | ConvertFrom-Json
    Log "Backup vom $($s.CreatedAt)"

    # 1. Energie
    if ($s.OriginalScheme) {
        powercfg /setactive $s.OriginalScheme | Out-Null
        Log "Energie: Schema $($s.OriginalScheme) wieder aktiv" 'Green'
    }
    if ($s.WingsScheme -and $s.WingsScheme -ne $s.OriginalScheme) {
        powercfg /delete $s.WingsScheme | Out-Null
        Log "Energie: Schema 'WingsConnect' gelöscht"
    }

    # 3. Windows Update
    foreach ($n in $WuNames) { Restore-RegValue $WuPath $n $s.WU.$n 'String' }
    try { Start-Service wuauserv -ErrorAction Stop } catch {}
    Log "Windows Update: Pause aufgehoben, Dienst gestartet" 'Green'

    # 4./5. Übermittlungsoptimierung, Store
    Restore-RegValue $DoPath    'DODownloadMode' $s.DODownloadMode 'DWord'
    Restore-RegValue $StorePath 'AutoDownload'   $s.StoreAutoDownload 'DWord'
    Log "Übermittlungsoptimierung und Store-Updates: Ausgangswerte wiederhergestellt" 'Green'

    # 6. Apps
    foreach ($app in $s.StoppedApps) {
        if ($app.Name -in 'Dropbox', 'OneDrive' -and $app.Path -and (Test-Path $app.Path)) {
            if ($app.Name -eq 'OneDrive') { Start-Process $app.Path -ArgumentList '/background' }
            else                          { Start-Process $app.Path }
            Log "App gestartet: $($app.Name)" 'Green'
        }
    }

    # 7. Zeitdienst
    if ($s.W32TimeWasRunning -eq $false) { try { Stop-Service w32time -ErrorAction Stop } catch {} }

    Remove-Item $BackupFile -Force
    Log "Backup entfernt. Fertig." 'Green'
    Show-Status
    exit 0
}

# ================================================================== PREPARE
Log "=== Wings Connect: Laptop für die Messung vorbereiten ===" 'Cyan'
if (Test-Path $BackupFile) {
    Log "Es gibt bereits ein Backup ($BackupFile)." 'Yellow'
    Log "Der Laptop ist vermutlich schon vorbereitet. Erst '-Restore' ausführen oder die Datei löschen." 'Yellow'
    Show-Status
    exit 1
}

# --- Ausgangszustand einsammeln und sichern, BEVOR etwas geändert wird
$state = [ordered]@{
    CreatedAt         = (Get-Date).ToString('s')
    OriginalScheme    = Get-ActiveSchemeGuid
    WingsScheme       = $null
    WU                = [ordered]@{}
    DODownloadMode    = Get-RegValue $DoPath 'DODownloadMode'
    StoreAutoDownload = Get-RegValue $StorePath 'AutoDownload'
    StoppedApps       = @()
    W32TimeWasRunning = ((Get-Service w32time).Status -eq 'Running')
}
foreach ($n in $WuNames) { $state.WU[$n] = Get-RegValue $WuPath $n }

$procs = Get-Process | Where-Object { $AppNames -contains $_.ProcessName }
$state.StoppedApps = @($procs | Group-Object ProcessName | ForEach-Object {
    [ordered]@{ Name = $_.Name; Path = ($_.Group | Select-Object -First 1).Path }
})

$state | ConvertTo-Json -Depth 4 | Set-Content -Path $BackupFile -Encoding UTF8
Log "Ausgangszustand gesichert: $BackupFile"

# --- 1. Energie
Log ""
Log "[1] Energieschema" 'Cyan'
$dup = (powercfg /duplicatescheme $state.OriginalScheme) -join ' '
$new = [regex]::Match($dup, $GuidRegex).Value
if (-not $new) {
    Log "  Konnte Schema nicht duplizieren – ändere das aktive Schema direkt." 'Yellow'
    $new = $state.OriginalScheme
} else {
    powercfg /changename $new 'WingsConnect' 'Messflug: kein Standby, WLAN volle Leistung' | Out-Null
    powercfg /setactive $new | Out-Null
}
$state.WingsScheme = $new
$state | ConvertTo-Json -Depth 4 | Set-Content -Path $BackupFile -Encoding UTF8

powercfg /change standby-timeout-ac 0   | Out-Null
powercfg /change standby-timeout-dc 0   | Out-Null
powercfg /change hibernate-timeout-ac 0 | Out-Null
powercfg /change hibernate-timeout-dc 0 | Out-Null
powercfg /change monitor-timeout-ac 15  | Out-Null
powercfg /change monitor-timeout-dc 15  | Out-Null
powercfg /attributes SUB_BUTTONS LIDACTION -ATTRIB_HIDE | Out-Null   # Einstellung ist hier versteckt → einblenden
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0 | Out-Null
powercfg /setdcvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0 | Out-Null
powercfg /setacvalueindex SCHEME_CURRENT $WifiPowerSub $WifiPowerSet 0 | Out-Null
powercfg /setdcvalueindex SCHEME_CURRENT $WifiPowerSub $WifiPowerSet 0 | Out-Null
powercfg /setactive SCHEME_CURRENT | Out-Null
Log "  Schema 'WingsConnect' aktiv: Standby/Ruhezustand nie, Zuklappen = nichts, WLAN max. Leistung, Bildschirm aus nach 15 Min." 'Green'

# --- 2. WLAN-Adapter (best effort)
Log ""
Log "[2] WLAN-Adapter Energieverwaltung" 'Cyan'
try {
    $wifi = Get-NetAdapter -Physical -ErrorAction Stop |
            Where-Object { $_.Status -eq 'Up' -and $_.InterfaceDescription -match 'Wireless|Wi-?Fi|WLAN|802\.11' } |
            Select-Object -First 1
    if ($wifi) {
        Set-NetAdapterPowerManagement -Name $wifi.Name -AllowComputerToTurnOffDevice Disabled -ErrorAction Stop
        Log "  '$($wifi.Name)': Computer darf Gerät nicht mehr ausschalten" 'Green'
    } else {
        Log "  Kein aktiver WLAN-Adapter gefunden – übersprungen" 'Yellow'
    }
} catch {
    Log "  Nicht änderbar ($($_.Exception.Message.Trim())) – übersprungen, Energieschema deckt das WLAN-Sparen ab" 'Yellow'
}

# --- 3. Windows Update
Log ""
Log "[3] Windows Update pausieren (7 Tage)" 'Cyan'
$nowUtc = (Get-Date).ToUniversalTime()
$start  = $nowUtc.ToString('yyyy-MM-ddTHH:mm:ssZ')
$end    = $nowUtc.AddDays(7).ToString('yyyy-MM-ddTHH:mm:ssZ')
foreach ($n in $WuNames) {
    if ($n -like '*StartTime') { Set-RegValue $WuPath $n $start 'String' } else { Set-RegValue $WuPath $n $end 'String' }
}
foreach ($svc in 'wuauserv', 'UsoSvc', 'DoSvc') {
    try { Stop-Service $svc -Force -ErrorAction Stop; Log "  Dienst $svc gestoppt" } catch { Log "  Dienst $svc: $($_.Exception.Message.Trim())" 'Yellow' }
}
Log "  Pause bis $end" 'Green'

# --- 4. Übermittlungsoptimierung
Log ""
Log "[4] Übermittlungsoptimierung: kein Peer-Upload" 'Cyan'
Set-RegValue $DoPath 'DODownloadMode' 0 'DWord'
Log "  DODownloadMode = 0 (nur HTTP, kein P2P)" 'Green'

# --- 5. Store
Log ""
Log "[5] Microsoft Store: automatische App-Updates aus" 'Cyan'
Set-RegValue $StorePath 'AutoDownload' 2 'DWord'
Log "  AutoDownload = 2" 'Green'

# --- 6. Apps
Log ""
Log "[6] Cloud-Sync und Hintergrund-Apps beenden" 'Cyan'
if ($procs) {
    foreach ($p in $procs) { try { Stop-Process -Id $p.Id -Force -ErrorAction Stop } catch {} }
    Log ("  Beendet: " + (($state.StoppedApps | ForEach-Object { $_.Name }) -join ', ')) 'Green'
} else {
    Log "  Keine der überwachten Apps lief" 'Green'
}

# --- 7. Zeit
Log ""
Log "[7] Uhrzeit synchronisieren" 'Cyan'
try {
    $t = Get-Service w32time -ErrorAction Stop
    if ($t.StartType -eq 'Disabled') { Set-Service w32time -StartupType Manual }
    if ($t.Status -ne 'Running') { Start-Service w32time -ErrorAction Stop }
    $r = (w32tm /resync /nowait) -join ' '
    Log "  $r" 'Green'
} catch {
    Log "  Zeitsync fehlgeschlagen: $($_.Exception.Message.Trim())" 'Yellow'
}

Log ""
Log "Fertig. Zurücksetzen nach dem Flug:  .\prepare_laptop.ps1 -Restore" 'Cyan'
Show-Status
exit 0
