# WinSecSweep.ps1  v1.2 hardened

[CmdletBinding()]
param(
  [string]$OutDir,
  [switch]$Quick,
  [switch]$Full
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function SafeCount($x) { if ($null -eq $x) { 0 } else { @($x).Count } }
function IsProp($o,$n) { try { $o -and $o.PSObject.Properties.Name -contains $n } catch { $false } }
function SafeHas($o,$n) { try { $o -and ($o | Get-Member -Name $n -ErrorAction Stop) } catch { $null } }

function New-Result {
  param([string]$Area,[string]$Check,[string]$Severity,[string]$Status,[string]$Recommendation,[hashtable]$Data)
  [pscustomobject]@{ Area=$Area; Check=$Check; Severity=$Severity; Status=$Status; Recommendation=$Recommendation; Data=$Data }
}

function Test-Admin {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  $p = New-Object Security.Principal.WindowsPrincipal($id)
  $p.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
}

function Convert-ToDateSafe { param($v)
  if ($null -eq $v -or $v -eq '') { return $null }
  if ($v -is [datetime]) { return $v }
  try { return [Management.ManagementDateTimeConverter]::ToDateTime([string]$v) } catch {
    try { return [datetime]$v } catch { return $null }
  }
}

function Get-OSInfo {
  $os = Get-CimInstance Win32_OperatingSystem
  $install = Convert-ToDateSafe $os.InstallDate
  $boot    = Convert-ToDateSafe $os.LastBootUpTime
  $uptimeH = if ($boot) { [int]((New-TimeSpan -Start $boot -End (Get-Date)).TotalHours) } else { $null }
  [pscustomobject]@{
    Caption=$os.Caption; Version=$os.Version; Build=$os.BuildNumber
    InstallDate=$install; LastBoot=$boot; UptimeHours=$uptimeH
  }
}

function Get-DefenderStatus {
  try {
    $mp = Get-MpComputerStatus
    $age = $null
    try {
      $age = [int]((Get-Date) - $mp.AntivirusSignatureLastUpdated).TotalHours
    } catch {
      $age = $null
    }
    return [pscustomobject]@{
      RealTime          = $mp.RealTimeProtectionEnabled
      BehaviorMonitor   = $mp.BehaviorMonitorEnabled
      Ioav              = $mp.IoavProtectionEnabled
      Antispyware       = $mp.AntispywareEnabled
      Antimalware       = $mp.AntivirusEnabled
      AMServiceEnabled  = $mp.AMServiceEnabled
      SignatureAgeHours = $age
      EngineVersion     = $mp.AMEngineVersion
      SigVersion        = $mp.AntivirusSignatureVersion
    }
  } catch {
    return $null
  }
}


function Get-FirewallStatus { Get-NetFirewallProfile | Select-Object Name,Enabled,DefaultInboundAction,DefaultOutboundAction }

function Test-RDPEnabled {
  $val = Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server' -Name 'fDenyTSConnections' -ErrorAction SilentlyContinue
  if ($null -eq $val) { return $null }
  [bool](-not $val.fDenyTSConnections)
}

function Test-SMB1Disabled {
  try {
    $opt = Get-WindowsOptionalFeature -Online -FeatureName SMB1Protocol -ErrorAction Stop
    ($opt.State -eq 'Disabled')
  } catch { $null }
}

function Get-SMBServerConfig { try { Get-SmbServerConfiguration } catch { $null } }

function Get-TLSConfig {
  $base = 'HKLM:\SYSTEM\CurrentControlSet\Control\SecurityProviders\SCHANNEL\Protocols'
  $names = 'SSL 3.0','TLS 1.0','TLS 1.1','TLS 1.2','TLS 1.3'
  $roles = 'Client','Server'
  $out = @()
  foreach ($n in $names) {
    foreach ($r in $roles) {
      $p = Join-Path $base "$n\$r"
      $enabled = $null
      if (Test-Path $p) {
        $vals = Get-ItemProperty $p -ErrorAction SilentlyContinue
        if (IsProp $vals 'Enabled') { $enabled = [int]$vals.Enabled } else { $enabled = $null }
      }
      $out += [pscustomobject]@{Protocol=$n; Role=$r; Enabled=$enabled}
    }
  }
  $out
}

function Get-ExecutionPolicyState {
  [pscustomobject]@{
    MachinePolicy = (Get-ExecutionPolicy -Scope MachinePolicy -ErrorAction SilentlyContinue)
    UserPolicy    = (Get-ExecutionPolicy -Scope UserPolicy -ErrorAction SilentlyContinue)
    Process       = (Get-ExecutionPolicy -Scope Process -ErrorAction SilentlyContinue)
    CurrentUser   = (Get-ExecutionPolicy -Scope CurrentUser -ErrorAction SilentlyContinue)
    LocalMachine  = (Get-ExecutionPolicy -Scope LocalMachine -ErrorAction SilentlyContinue)
    Effective     = (Get-ExecutionPolicy)
  }
}

function Get-AdminGroupMembers { try { Get-LocalGroupMember -Group 'Administrators' -ErrorAction Stop | Select-Object Name,ObjectClass,PrincipalSource } catch { @() } }
function Test-GuestEnabled { try { $g=Get-LocalUser -Name 'Guest' -ErrorAction Stop; $g.Enabled } catch { $false } }

function Get-BitLockerStatus {
  try { Get-BitLockerVolume -ErrorAction Stop | Select-Object MountPoint,VolumeStatus,ProtectionStatus,EncryptionMethod,LockStatus,PercentageEncrypted }
  catch {
    $raw = cmd /c 'manage-bde -status' 2>$null
    [pscustomobject]@{ Raw = ($raw -join "`n") }
  }
}

function Get-NetworkBasics {
  $adapters = Get-NetIPConfiguration | Where-Object { $_.IPv4Address }
  $adapters | ForEach-Object {
    $iface = $_.InterfaceAlias
    $ipv4  = $null; $pref=$null; $gw=$null; $dnsList=$null; $netProfile=$null; $linkSpeed=$null
    try { $ipv4 = $_.IPv4Address.IPAddress; $pref = $_.IPv4Address.PrefixLength } catch {}
    try { if ($_.IPv4DefaultGateway -and (SafeHas $_.IPv4DefaultGateway 'NextHop')) { $gw = $_.IPv4DefaultGateway.NextHop } } catch {}
    try { $dns = Get-DnsClientServerAddress -InterfaceAlias $iface -AddressFamily IPv4 -ErrorAction Stop; if ($dns -and $dns.ServerAddresses) { $dnsList = ($dns.ServerAddresses -join ',') } } catch {}
    try { $np = Get-NetConnectionProfile -InterfaceAlias $iface -ErrorAction Stop; $netProfile = $np.NetworkCategory } catch {}
    try { $na = Get-NetAdapter -Name $iface -ErrorAction Stop; $linkSpeed = $na.LinkSpeed } catch {}
    [pscustomobject]@{ Interface=$iface; IPv4=$ipv4; Prefix=$pref; GW=$gw; DNS=$dnsList; NetProfile=$netProfile; LinkSpeed=$linkSpeed }
  }
}

function Get-ListeningPorts {
  $listens = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue
  $procs = @{}
  foreach ($p in (Get-Process)) { $procs[$p.Id] = $p.ProcessName }
  $listens | ForEach-Object {
    [pscustomobject]@{
      LocalAddress=$_.LocalAddress; LocalPort=$_.LocalPort; OwningProcess=$_.OwningProcess; ProcessName=$procs[$_.OwningProcess]
    }
  } | Sort-Object LocalPort
}

function Get-StartupEntries {
  $items = @()
  $paths = @("$env:ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp", "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup")
  foreach ($p in $paths) { if (Test-Path $p) { Get-ChildItem -Path $p -ErrorAction SilentlyContinue | ForEach-Object { $items += [pscustomobject]@{ Location='StartupFolder'; Path=$_.FullName } } } }
  $runKeys = @('HKLM:\Software\Microsoft\Windows\CurrentVersion\Run','HKLM:\Software\Microsoft\Windows\CurrentVersion\RunOnce','HKCU:\Software\Microsoft\Windows\CurrentVersion\Run','HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce')
  foreach ($rk in $runKeys) {
    if (Test-Path $rk) {
      $vals = Get-ItemProperty -Path $rk
      $vals.PSObject.Properties | Where-Object { $_.Name -notmatch 'PSPath|PSParentPath|PSChildName|PSDrive|PSProvider' } |
        ForEach-Object { $items += [pscustomobject]@{ Location=$rk; Name=$_.Name; Value=$_.Value } }
    }
  }
  $items
}

function Get-InstalledPrograms {
  function Get-Prop { param($o,[string]$n)
    if ($null -eq $o) { return $null }
    if ($o.PSObject.Properties.Name -contains $n) { return $o.$n }
    return $null
  }

  $roots = @(
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
    'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall',
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall'
  )

  $list = @()
  foreach ($r in $roots) {
    if (Test-Path $r) {
      Get-ChildItem $r -ErrorAction SilentlyContinue | ForEach-Object {
        $p = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
        $name = Get-Prop $p 'DisplayName'
        if ($name) {
          $list += [pscustomobject]@{
            Name            = $name
            Version         = Get-Prop $p 'DisplayVersion'
            Publisher       = Get-Prop $p 'Publisher'
            InstallDate     = Get-Prop $p 'InstallDate'      # may be null or yyyyMMdd
            UninstallString = Get-Prop $p 'UninstallString'
          }
        }
      }
    }
  }
  $list | Sort-Object Name -Unique
}

function Get-WinUpdateSummary {
  Get-CimInstance Win32_QuickFixEngineering | Sort-Object -Property InstalledOn -Descending | Select-Object -First 10 Description,HotFixID,InstalledOn
}

function Test-LLMNR {
  $p = 'HKLM:\Software\Policies\Microsoft\Windows NT\DNSClient'
  if (Test-Path $p) {
    $v = Get-ItemProperty $p -Name EnableMulticast -ErrorAction SilentlyContinue
    if ($null -ne $v) { return ([int]$v.EnableMulticast -eq 0) }
  }
  $false
}

function Test-NetBIOS {
  $keys = Get-ChildItem 'HKLM:\SYSTEM\CurrentControlSet\Services\NetBT\Parameters\Interfaces' -ErrorAction SilentlyContinue
  if ($keys) {
    $all = $keys | ForEach-Object { $n = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue; [pscustomobject]@{ Name=$_.PSChildName; NetbiosOptions=$n.NetbiosOptions } }
    $disabled = $all | Where-Object { $_.NetbiosOptions -eq 2 }
    return [pscustomobject]@{ DisabledCount= (SafeCount $disabled); Total=(SafeCount $all) }
  }
  $null
}

function Get-RiskyApps {
  param([object[]]$Programs)
  $patterns = @(
    'Java 7','Java 8','JRE','Flash Player','Silverlight',
    'uTorrent','BitTorrent','qBittorrent',
    'TeamViewer','AnyDesk','UltraVNC','TightVNC',
    '7-Zip 16','7-Zip 17','WinRAR 5.','WinRAR 4.',
    'Java(TM)','OpenJDK 1.'
  )
  $hits = @()
  foreach ($p in @($Programs)) {
    foreach ($pat in $patterns) {
      if ($p.Name -like "*$pat*") { $hits += $p; break }
    }
  }
  $hits | Sort-Object Name -Unique
}


# Output setup
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if (-not $OutDir) { $OutDir = Join-Path -Path (Get-Location) -ChildPath "WinSecSweep-Report-$stamp" }
New-Item -Path $OutDir -ItemType Directory -Force | Out-Null
$jsonPath = Join-Path $OutDir "WinSecSweep-$stamp.json"
$mdPath = Join-Path $OutDir "WinSecSweep-$stamp.md"

$results = New-Object System.Collections.Generic.List[object]
$facts = [ordered]@{}

# Admin
$admin = Test-Admin
$facts.Admin = $admin
if (-not $admin) { $results.Add((New-Result 'Meta' 'Run as Administrator' 'High' 'Fail' 'Re-run PowerShell elevated for full visibility.' @{})) }

# OS
$os = Get-OSInfo; $facts.OS = $os
$results.Add((New-Result 'System' 'OS version' 'Info' 'Info' ("Windows {0} build {1}. Uptime {2}h." -f $os.Caption,$os.Build,$os.UptimeHours) @{}))

# Defender
$def = Get-DefenderStatus; $facts.Defender = $def
if ($null -eq $def) {
  $results.Add((New-Result 'AV' 'Microsoft Defender status' 'Medium' 'Warn' 'Could not query Defender. If using 3rd party AV, verify it is active.' @{}))
} else {
  if (-not $def.RealTime) { $results.Add((New-Result 'AV' 'Real-time protection' 'High' 'Fail' 'Enable Defender real-time protection or ensure AV is active.' @{})) }
  else { $results.Add((New-Result 'AV' 'Real-time protection' 'Low' 'Pass' 'Real-time protection is enabled.' @{})) }
  if ($def.SignatureAgeHours -and $def.SignatureAgeHours -gt 24) { $results.Add((New-Result 'AV' 'Signatures fresh' 'Medium' 'Warn' 'Update AV signatures. Older than 24h.' @{ Hours=$def.SignatureAgeHours })) }
  elseif ($def.SignatureAgeHours -ne $null) { $results.Add((New-Result 'AV' 'Signatures fresh' 'Low' 'Pass' 'Signatures updated within 24h.' @{ Hours=$def.SignatureAgeHours })) }
}

# Firewall
$fw = Get-FirewallStatus; $facts.Firewall = $fw
foreach ($p in @($fw)) {
  if (-not $p.Enabled) { $results.Add((New-Result 'Firewall' ("Profile {0}" -f $p.Name) 'High' 'Fail' 'Enable Windows Firewall for this profile.' @{})) }
  else { $results.Add((New-Result 'Firewall' ("Profile {0}" -f $p.Name) 'Low' 'Pass' ("Inbound {0}, Outbound {1}." -f $p.DefaultInboundAction,$p.DefaultOutboundAction) @{})) }
}

# RDP
$rdp = Test-RDPEnabled; $facts.RDPEnabled = $rdp
if ($rdp -eq $true) { $results.Add((New-Result 'RemoteAccess' 'RDP hardened' 'High' 'Warn' 'RDP enabled. Restrict by firewall, NLA, strong passwords or disable.' @{})) }
elseif ($rdp -eq $false) { $results.Add((New-Result 'RemoteAccess' 'RDP hardened' 'Low' 'Pass' 'RDP disabled.' @{})) }

# SMB
$smb1off = Test-SMB1Disabled; $facts.SMB1Disabled = $smb1off
if ($smb1off -eq $true) { $results.Add((New-Result 'SMB' 'SMBv1 disabled' 'Low' 'Pass' 'SMBv1 is disabled.' @{})) }
elseif ($smb1off -eq $false) { $results.Add((New-Result 'SMB' 'SMBv1 disabled' 'High' 'Fail' 'Disable SMBv1. Legacy and vulnerable.' @{})) }
else { $results.Add((New-Result 'SMB' 'SMBv1 disabled' 'Medium' 'Warn' 'Could not query SMBv1 state. Run as Administrator for full results.' @{})) }

$smbcfg = Get-SMBServerConfig
if ($smbcfg) {
  if (IsProp $smbcfg 'EnableSMB2Protocol') { if (-not $smbcfg.EnableSMB2Protocol) { $results.Add((New-Result 'SMB' 'SMBv2/v3 enabled' 'High' 'Fail' 'Enable SMBv2/3.' @{})) } }
  if (IsProp $smbcfg 'EnableInsecureGuestLogons') { if ($smbcfg.EnableInsecureGuestLogons) { $results.Add((New-Result 'SMB' 'Insecure guest logons' 'High' 'Fail' 'Disable insecure guest SMB logons.' @{})) } }
}

# TLS
$tls = Get-TLSConfig; $facts.TLS = $tls
$bad = $tls | Where-Object { ($_.Protocol -in 'SSL 3.0','TLS 1.0','TLS 1.1') -and $_.Enabled -eq 1 }
if (SafeCount $bad -gt 0) { $results.Add((New-Result 'TLS' 'Legacy TLS/SSL disabled' 'High' 'Fail' 'Disable SSL 3.0, TLS 1.0, TLS 1.1 unless required.' @{})) }
else { $results.Add((New-Result 'TLS' 'Legacy TLS/SSL disabled' 'Low' 'Pass' 'No explicit legacy protocol enablement detected.' @{})) }

# PS Execution Policy
$ep = Get-ExecutionPolicyState; $facts.ExecutionPolicy=$ep
if ($ep.Effective -in 'Unrestricted','Bypass') { $results.Add((New-Result 'PowerShell' 'Execution policy' 'Medium' 'Warn' 'Set to RemoteSigned or AllSigned unless intentionally loosened.' @{ Effective=$ep.Effective })) }
else { $results.Add((New-Result 'PowerShell' 'Execution policy' 'Low' 'Pass' ("Effective policy: {0}" -f $ep.Effective) @{})) }

# Local Admins
$admins = Get-AdminGroupMembers; $facts.LocalAdmins=$admins
$nonMS = @($admins | Where-Object { $_.Name -notmatch 'Administrators|Domain Admins|Enterprise Admins|SYSTEM|Administrator' })
if (SafeCount $nonMS -gt 0) { $results.Add((New-Result 'Accounts' 'Administrators group hygiene' 'Medium' 'Warn' 'Review and prune unexpected local admins.' @{ Members = ($nonMS.Name -join ', ') })) }
else { $results.Add((New-Result 'Accounts' 'Administrators group hygiene' 'Low' 'Pass' 'No unexpected local admins detected.' @{})) }

# Guest
$guestOn = Test-GuestEnabled; $facts.GuestEnabled=$guestOn
if ($guestOn) { $results.Add((New-Result 'Accounts' 'Guest account' 'High' 'Fail' 'Disable Guest account.' @{})) } else { $results.Add((New-Result 'Accounts' 'Guest account' 'Low' 'Pass' 'Guest is disabled.' @{})) }

# BitLocker
$bit = Get-BitLockerStatus; $facts.BitLocker=$bit
if ($bit -is [array]) {
  foreach ($v in $bit) {
    if ($v.ProtectionStatus -ne 'On') { $results.Add((New-Result 'Disk' ("BitLocker {0}" -f $v.MountPoint) 'High' 'Warn' 'Enable BitLocker where possible.' @{ Status=$v.ProtectionStatus })) }
    else { $results.Add((New-Result 'Disk' ("BitLocker {0}" -f $v.MountPoint) 'Low' 'Pass' 'BitLocker protection is On.' @{})) }
  }
} else { $results.Add((New-Result 'Disk' 'BitLocker status' 'Info' 'Info' 'Could not parse BitLocker via cmdlets, raw captured.' @{})) }

# Network
$net = Get-NetworkBasics; $facts.Network=$net
foreach ($n in @($net)) {
  if ($n.NetProfile -eq 'Public') { $results.Add((New-Result 'Network' ("Profile {0}" -f $n.Interface) 'Low' 'Pass' 'Public profile reduces exposure on untrusted networks.' @{ Category=$n.NetProfile })) }
  else { $results.Add((New-Result 'Network' ("Profile {0}" -f $n.Interface) 'Medium' 'Warn' 'Private or Domain is fine at home. Ensure firewall enabled.' @{ Category=$n.NetProfile })) }
  if ($n.LinkSpeed -and ($n.LinkSpeed -like '*100Mbps*')) { $results.Add((New-Result 'Network' ("Link speed {0}" -f $n.Interface) 'Medium' 'Warn' 'Link negotiated at 100 Mbps. Check cable or switch.' @{ LinkSpeed=$n.LinkSpeed })) }
}

# LLMNR, NetBIOS
$llmnrOff = Test-LLMNR; $facts.LLMNRDisabled=$llmnrOff
if (-not $llmnrOff) { $results.Add((New-Result 'NameResolution' 'LLMNR disabled' 'Low' 'Warn' 'Disable LLMNR via policy/registry to reduce spoofing risk.' @{})) }
else { $results.Add((New-Result 'NameResolution' 'LLMNR disabled' 'Low' 'Pass' 'LLMNR appears disabled.' @{})) }

$nb = Test-NetBIOS; $facts.NetBIOS=$nb
if ($nb -and $nb.Total -gt 0 -and $nb.DisabledCount -lt $nb.Total) {
  $results.Add((New-Result 'NameResolution' 'NetBIOS over TCP' 'Low' 'Warn' 'Disable NetBIOS on adapters that do not require it.' @{ Disabled=$nb.DisabledCount; Total=$nb.Total }))
}

# Listening ports
$listen = Get-ListeningPorts; $facts.Listening=$listen
$wild = @($listen | Where-Object { $_.LocalAddress -in @('0.0.0.0','::') })
if (SafeCount $wild -gt 0) { $results.Add((New-Result 'Services' 'Wide listening sockets' 'Medium' 'Warn' 'Services bound to all interfaces. Verify exposure and firewall rules.' @{ Count=(SafeCount $wild) })) }

# Startup entries
$startup = Get-StartupEntries; $facts.Startup=$startup
$startupCount = SafeCount $startup
if ($startupCount -gt 0) { $results.Add((New-Result 'Persistence' 'Auto-start entries' 'Info' 'Info' 'Review startup items for unwanted software.' @{ Count=$startupCount })) }

# Installed programs and risk hints
$programs = Get-InstalledPrograms; $facts.Programs=$programs
$risky = @(Get-RiskyApps -Programs $programs)
if (SafeCount $risky -gt 0) { $results.Add((New-Result 'Apps' 'Potentially risky software' 'Medium' 'Warn' 'Uninstall or update legacy or remote-control software you do not need.' @{ Names = ($risky.Name -join ', ') })) }
else { $results.Add((New-Result 'Apps' 'Potentially risky software' 'Low' 'Pass' 'No common riskware detected by name match.' @{})) }

# Windows Update summary
$wu = Get-WinUpdateSummary; $facts.WindowsUpdate=$wu
if ($wu -and $wu[0]) {
  $latest = $wu[0]
  $installedOn = $null
  if ($latest.InstalledOn) { try { $installedOn = [datetime]$latest.InstalledOn } catch { $installedOn = "$($latest.InstalledOn)" } }
  $msg = if ($installedOn) { "Latest hotfix: $($latest.HotFixID) on $installedOn." } else { "Latest hotfix: $($latest.HotFixID) (date unavailable)." }
  $results.Add((New-Result 'Patching' 'Recent hotfixes present' 'Low' 'Pass' $msg @{}))
} else {
  $results.Add((New-Result 'Patching' 'Recent hotfixes present' 'Medium' 'Warn' 'Could not determine latest hotfix. Ensure Windows Update is functioning.' @{}))
}

# Optional deeper checks
if ($Full -and -not $Quick) {
  try {
    $tasks = Get-ScheduledTask -ErrorAction Stop | Where-Object { $_.TaskPath -notlike '\Microsoft\Windows\*' }
    $facts.ScheduledTasksNonMS = $tasks | Select-Object TaskName,TaskPath,State
    if (SafeCount $tasks -gt 0) { $results.Add((New-Result 'Persistence' 'Non-Microsoft scheduled tasks' 'Info' 'Info' 'Review non-Microsoft scheduled tasks for unwanted persistence.' @{ Count=(SafeCount $tasks) })) }
  } catch {
    $results.Add((New-Result 'Persistence' 'Scheduled tasks' 'Info' 'Info' 'Could not enumerate scheduled tasks.' @{}))
  }
}

# Score
$score = 100
foreach ($r in $results) {
  switch ($r.Severity) {
    'Critical' { if ($r.Status -ne 'Pass') { $score -= 25 } }
    'High'     { if ($r.Status -ne 'Pass') { $score -= 15 } }
    'Medium'   { if ($r.Status -ne 'Pass') { $score -= 7 } }
    'Low'      { if ($r.Status -eq 'Fail' -or $r.Status -eq 'Warn') { $score -= 2 } }
  }
}
if ($score -lt 0) { $score = 0 }
$facts.Score = $score

# Write JSON
$payload = [pscustomobject]@{ GeneratedAt=(Get-Date); Hostname=$env:COMPUTERNAME; IsAdmin=$admin; Facts=$facts; Findings=$results }
$payload | ConvertTo-Json -Depth 6 | Out-File -FilePath $jsonPath -Encoding UTF8

# Write Markdown without backtick pitfalls
$md = @()
$md += "# Windows Security Sweep"; $md += ""
$md += ("**Host:** {0}" -f $env:COMPUTERNAME)
$md += ("**Generated:** {0}" -f (Get-Date))
$md += ("**Score:** {0}/100" -f $score); $md += ""
$md += "## Summary"
$summary = $results | Group-Object Status | ForEach-Object { "- $($_.Name): $($_.Count)" }
$md += ($summary -join "`n"); $md += ""
$md += "## Key Facts"
$md += ("- OS: {0} build {1}" -f $os.Caption, $os.Build)
$md += ("- Uptime: {0} hours" -f $os.UptimeHours)
if ($def) { $md += ("- Defender real-time: {0}, Sig age: {1}h" -f $def.RealTime, $def.SignatureAgeHours) }
$md += ""; $md += "## Findings"
foreach ($r in $results) {
  $md += ("### [{0}] {1}" -f $r.Area, $r.Check)
  $md += ("- Severity: **{0}**" -f $r.Severity)
  $md += ("- Status: **{0}**" -f $r.Status)
  if ($r.Recommendation) { $md += ("- Fix: {0}" -f $r.Recommendation) }
  if ($r.Data -and (SafeCount $r.Data.Keys) -gt 0) {
    $jsonCompact = ($r.Data | ConvertTo-Json -Compress)
    $md += ("- Data: ``{0}``" -f $jsonCompact)
  }
  $md += ""
}
($md -join "`n") | Out-File -FilePath $mdPath -Encoding UTF8

Write-Host "Report written to:"
Write-Host ("  Markdown: {0}" -f $mdPath)
Write-Host ("  JSON:     {0}" -f $jsonPath)
