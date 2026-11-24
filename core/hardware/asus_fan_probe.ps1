# Lecture SEULE des réglages de ventilateurs du BIOS ASUS (interface WMI officielle ASUSManagement).
# Lancé par le Hub avec élévation (Windows demande l'autorisation) : aucune méthode Set* n'est appelée ici.
# Résultat : JSON écrit dans le fichier -Out (dossier data du Hub).
param([Parameter(Mandatory = $true)][string]$Out)
$ErrorActionPreference = 'Stop'
$result = [ordered]@{ date = (Get-Date).ToString('s'); ok = $false; erreur = ''; ventilateurs = @() }
try {
    $m = Get-CimInstance -Namespace root/wmi -ClassName ASUSManagement | Select-Object -First 1
    if (-not $m) { throw "interface ASUSManagement absente" }
    $fans = @()
    foreach ($ft in 0..15) {
        try {
            $p = Invoke-CimMethod -InputObject $m -MethodName GetFanPolicy -Arguments @{ FanType = [byte]$ft }
            if ($p.ErrorCode -ne 0) { continue }
            $entry = [ordered]@{ type = $ft; mode = "$($p.Mode)"; profil = "$($p.Profile)"; seuil_bas = $p.LowLimit; courbe = $null }
            try {
                $c = Invoke-CimMethod -InputObject $m -MethodName GetManualFanCurve -Arguments @{ FanType = [byte]$ft; Mode = "$($p.Mode)" }
                if ($c.ErrorCode -eq 0) {
                    $entry.courbe = [ordered]@{ bas = @($c.LowTemp, $c.LowDuty); milieu = @($c.MidTemp, $c.MidDuty); haut = @($c.HighTemp, $c.HighDuty) }
                } else { $entry.erreur_courbe = $c.ErrorCode }
            } catch { $entry.erreur_courbe = $_.Exception.Message }
            $fans += [pscustomobject]$entry
        } catch { continue }
    }
    $result.ventilateurs = $fans
    $result.ok = $true
} catch {
    $result.erreur = $_.Exception.Message
}
$result | ConvertTo-Json -Depth 5 | Set-Content -Path $Out -Encoding UTF8
