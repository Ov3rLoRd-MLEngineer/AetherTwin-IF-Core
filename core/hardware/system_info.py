"""État du PC pour l'Accueil (façon Gestionnaire des tâches) et pour Inoue : performance, stockage, périphériques,
fiche système, processus gourmands, mode d'alimentation, outils ASUS, capteurs.

Tout est lu **sans droits administrateur** : psutil, NVML (cartes NVIDIA), requêtes CIM de Windows (PowerShell,
lecture seule, délai maximal). Les actions (fermer un processus, changer de mode d'alimentation, ouvrir une fenêtre de
Windows ou un outil) ne partent que d'un clic dans le Hub, sur une liste fermée.

Capteurs de la carte mère : l'interface WMI `ASUSHW` de la carte est un accès matériel brut (ports, SMBus, mémoire),
réservé aux administrateurs : elle n'est **pas** utilisée. Les capteurs détaillés (températures, tensions,
ventilateurs) viennent de LibreHardwareMonitor s'il tourne avec son serveur web local (127.0.0.1:8085).
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psutil

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
HISTORY = 60  # points gardés pour les courbes (1 par seconde)

# Fenêtres de Windows que le Hub peut ouvrir (liste fermée).
WINDOWS_TARGETS: dict[str, tuple[str, str]] = {
    "ce_pc": ("Ce PC", "shell:MyComputerFolder"),
    "gestion_disques": ("Gestion des disques", "diskmgmt.msc"),
    "gestionnaire_taches": ("Gestionnaire des tâches", "taskmgr.exe"),
    "moniteur_ressources": ("Moniteur de ressources", "resmon.exe"),
    "gestionnaire_peripheriques": ("Gestionnaire de périphériques", "devmgmt.msc"),
    "peripheriques": ("Bluetooth et appareils", "ms-settings:connecteddevices"),
    "imprimantes": ("Imprimantes et scanners", "ms-settings:printers"),
    "a_propos": ("Paramètres > À propos", "ms-settings:about"),
    "alimentation": ("Options d'alimentation", "powercfg.cpl"),
    "son": ("Son", "mmsys.cpl"),
    "affichage": ("Affichage", "ms-settings:display"),
}

# Outils ASUS / CPUID, dans leurs dossiers d'installation par défaut.
PF = os.environ.get("ProgramFiles", r"C:\Program Files")
PF86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
# Pages officielles de téléchargement (vérifiées le 25/11/2026 ; GPU Tweak III : page donnée par Jérémy ; le
# moniteur et GPU-Z ASUS sont livrés avec GPU Tweak III).
GPU_TWEAK = "https://www.asus.com/campaign/GPU-Tweak-III/nafr-ar/index.php"
TOOLS: dict[str, dict[str, Any]] = {
    "armoury_crate": {"nom": "Armoury Crate", "role": "carte mère, ventilateurs (Fan Xpert), éclairage Aura",
                      "appx": "B9ECED6F.ArmouryCrate_qmba6cd70vzyy!App", "process": "ArmouryCrate.exe",
                      "telecharger": "https://www.asus.com/supportonly/armoury%20crate/helpdesk_download/"},
    "gpu_tweak": {"nom": "GPU Tweak III", "role": "fréquences, tension et ventilateurs de la carte graphique",
                  "paths": [rf"{PF86}\ASUS\GPUTweakIII\GPU Tweak III.exe", rf"{PF}\ASUS\GPUTweakIII\GPU Tweak III.exe"],
                  "process": "GPU Tweak III.exe", "telecharger": GPU_TWEAK},
    "gpu_tweak_monitor": {"nom": "Moniteur GPU Tweak III", "role": "courbes des capteurs de la carte graphique",
                          "paths": [rf"{PF86}\ASUS\GPUTweakIII\Monitor.exe"], "process": "Monitor.exe",
                          "telecharger": GPU_TWEAK},
    "gpu_z": {"nom": "GPU-Z (ASUS)", "role": "fiche technique et capteurs de la carte graphique",
              "paths": [rf"{PF86}\ASUS\GPUTweakIII\ASUSGPUZ.exe", rf"{PF}\TechPowerUp\GPU-Z\GPU-Z.exe"],
              "process": "ASUSGPUZ.exe", "telecharger": "https://www.techpowerup.com/gpuz/"},
    "cpu_z": {"nom": "ROG CPU-Z", "role": "processeur, carte mère, mémoire (SPD)",
              "paths": [rf"{PF}\CPUID\ROG CPU-Z\cpuz.exe", rf"{PF}\CPUID\CPU-Z\cpuz.exe"], "process": "cpuz.exe",
              "telecharger": "https://www.cpuid.com/softwares/cpu-z.html"},
    "lhm": {"nom": "LibreHardwareMonitor", "role": "capteurs détaillés de la carte mère (lus par le Hub)",
            "paths": [rf"{PF}\LibreHardwareMonitor\LibreHardwareMonitor.exe"], "process": "LibreHardwareMonitor.exe",
            "telecharger": "https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases"},
}

# Processus qu'Inoue ne propose jamais de fermer.
PROTECTED = {
    "system", "system idle process", "registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
    "services.exe", "lsass.exe", "svchost.exe", "dwm.exe", "explorer.exe", "fontdrvhost.exe", "sihost.exe",
    "ctfmon.exe", "audiodg.exe", "spoolsv.exe", "memory compression", "securityhealthservice.exe",
    "msmpeng.exe", "nissrv.exe", "taskmgr.exe", "conhost.exe", "runtimebroker.exe", "startmenuexperiencehost.exe",
    "searchhost.exe", "shellexperiencehost.exe", "textinputhost.exe", "lsaiso.exe", "wudfhost.exe",
    "ollama.exe", "ollama app.exe", "python.exe", "pythonw.exe",  # le Hub et ses modèles
}

PERIPHERAL_CLASSES = {
    "Keyboard": "Claviers", "Mouse": "Souris et pointage", "Monitor": "Écrans", "AudioEndpoint": "Audio",
    "Bluetooth": "Bluetooth", "Camera": "Caméras", "Image": "Caméras", "Printer": "Imprimantes",
    "PrintQueue": "Imprimantes", "XboxComposite": "Manettes", "HIDClass": "Manettes", "WPD": "Appareils portables",
    "Net": "Réseau",
}

GAMEPAD = re.compile(r"manette|game|controller|joystick|xbox|dualsense|dualshock", re.I)
VIRTUAL_NET = re.compile(r"virtual|miniport|wan|kernel debug|bluetooth device|hyper-v|tap-", re.I)


def _ps(script: str, timeout: float = 30.0) -> Any:
    """Exécute une requête PowerShell en lecture seule et renvoie son JSON (None en cas d'échec ou de délai)."""
    full = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; $ErrorActionPreference = 'SilentlyContinue'; " + script
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", full], capture_output=True,
                             timeout=timeout, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
        text = out.stdout.decode("utf-8", "replace").strip()
        return json.loads(text) if text else None
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [] if value is None else [value]


# ---------------------------------------------------------------- mesures en direct
class SystemSampler:
    """Mesure le PC une fois par seconde (seulement pendant qu'on le regarde) et garde 60 points d'historique."""

    def __init__(self, gpus: Callable[[], list[dict[str, Any]]] | None = None, idle_stop_s: float = 60.0,
                 interval_s: float = 1.0) -> None:
        self.gpus = gpus or nvml_details
        self.idle_stop_s, self.interval_s = idle_stop_s, interval_s
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._last_read = 0.0
        self._snapshot: dict[str, Any] = {}
        self._history: dict[str, deque[float]] = {}
        self._io: tuple[float, dict[str, Any], dict[str, Any]] | None = None
        self._counts: dict[str, int] = {}
        self._counts_at = 0.0

    def read(self) -> dict[str, Any]:
        """Dernière mesure + historique ; démarre la mesure si besoin."""
        with self._lock:
            self._last_read = time.monotonic()
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="system-sampler", daemon=True)
                self._thread.start()
            snapshot = dict(self._snapshot)
            history = {key: list(values) for key, values in self._history.items()}
        if not snapshot:
            snapshot = self.sample()
        return {**snapshot, "historique": history}

    def _loop(self) -> None:
        psutil.cpu_percent(percpu=True)  # première mesure de référence
        while time.monotonic() - self._last_read < self.idle_stop_s:
            time.sleep(self.interval_s)
            try:
                self.sample()
            except Exception:  # noqa: BLE001, S112 — une mesure ratée ne doit pas arrêter la boucle
                continue

    def _push(self, key: str, value: float | None) -> None:
        if value is None:
            return
        self._history.setdefault(key, deque(maxlen=HISTORY)).append(round(float(value), 1))

    def sample(self) -> dict[str, Any]:
        now = time.monotonic()
        per_core = psutil.cpu_percent(percpu=True)
        cpu = round(sum(per_core) / len(per_core), 1) if per_core else 0.0
        freq = psutil.cpu_freq()
        mem, swap = psutil.virtual_memory(), psutil.swap_memory()
        disks = psutil.disk_io_counters(perdisk=True) or {}
        nets = psutil.net_io_counters(pernic=True) or {}
        stats = psutil.net_if_stats()
        rates_disk: dict[str, dict[str, float]] = {}
        rates_net: dict[str, dict[str, float]] = {}
        if self._io:
            then, old_disks, old_nets = self._io
            span = max(now - then, 0.001)
            for name, io in disks.items():
                if name in old_disks:
                    old = old_disks[name]
                    busy = getattr(io, "busy_time", None)
                    rates_disk[name] = {
                        "lecture_ko_s": round((io.read_bytes - old.read_bytes) / 1024 / span, 1),
                        "ecriture_ko_s": round((io.write_bytes - old.write_bytes) / 1024 / span, 1),
                        "actif_pct": round(min(100.0, (busy - old.busy_time) / 10 / span), 1)
                        if busy is not None and getattr(old, "busy_time", None) is not None else None,
                    }
            for name, io in nets.items():
                if name in old_nets and stats.get(name) and stats[name].isup and "loopback" not in name.lower():
                    old = old_nets[name]
                    rates_net[name] = {"recu_ko_s": round((io.bytes_recv - old.bytes_recv) / 1024 / span, 1),
                                       "envoye_ko_s": round((io.bytes_sent - old.bytes_sent) / 1024 / span, 1),
                                       "vitesse_mbit": stats[name].speed}
        self._io = (now, disks, nets)
        if now - self._counts_at > 5 or not self._counts:
            self._counts, self._counts_at = process_counts(), now
        gpus = self.gpus()
        snapshot = {
            "horodatage": time.time(),
            "cpu": {"utilisation_pct": cpu, "coeurs_pct": [round(v, 1) for v in per_core],
                    "frequence_mhz": round(freq.current) if freq else None,
                    "frequence_max_mhz": round(freq.max) if freq and freq.max else None,
                    **self._counts, "duree_fonctionnement_s": round(time.time() - psutil.boot_time())},
            "memoire": {"utilisee_go": round(mem.used / 2**30, 1), "totale_go": round(mem.total / 2**30, 1),
                        "disponible_go": round(mem.available / 2**30, 1), "pct": mem.percent,
                        "echange_go": round(swap.used / 2**30, 1), "echange_total_go": round(swap.total / 2**30, 1)},
            "disques": rates_disk, "reseau": rates_net, "gpus": gpus,
        }
        with self._lock:
            self._snapshot = snapshot
            self._push("cpu", cpu)
            self._push("memoire", mem.percent)
            for name, rate in rates_disk.items():
                self._push(f"disque:{name}", rate["actif_pct"] if rate["actif_pct"] is not None
                           else min(100.0, (rate["lecture_ko_s"] + rate["ecriture_ko_s"]) / 1024))
            for name, rate in rates_net.items():
                self._push(f"reseau:{name}", rate["recu_ko_s"] + rate["envoye_ko_s"])
            for gpu in gpus:
                self._push(f"gpu:{gpu['index']}", gpu.get("utilisation_pct"))
        return snapshot


def process_counts() -> dict[str, int]:
    processes = threads = handles = 0
    for proc in psutil.process_iter(["num_threads", "num_handles"]):
        processes += 1
        threads += proc.info.get("num_threads") or 0
        handles += proc.info.get("num_handles") or 0
    return {"processus": processes, "threads": threads, "handles": handles}


_NVML: Any = None


def nvml_details() -> list[dict[str, Any]]:
    """Détails des cartes NVIDIA (fréquences, ventilateur, consommation, températures) ; liste vide sans NVML."""
    global _NVML
    try:
        if _NVML is None:
            import pynvml

            pynvml.nvmlInit()
            _NVML = pynvml
        nvml = _NVML
        result = []
        for index in range(nvml.nvmlDeviceGetCount()):
            h = nvml.nvmlDeviceGetHandleByIndex(index)

            def read(fn: Callable[[], Any], h: Any = h) -> Any:  # noqa: ARG001 — mesure absente : None
                try:
                    return fn()
                except Exception:  # noqa: BLE001
                    return None

            mem = read(lambda h=h: nvml.nvmlDeviceGetMemoryInfo(h))
            util = read(lambda h=h: nvml.nvmlDeviceGetUtilizationRates(h))
            power = read(lambda h=h: nvml.nvmlDeviceGetPowerUsage(h))
            limit = read(lambda h=h: nvml.nvmlDeviceGetEnforcedPowerLimit(h))
            name = read(lambda h=h: nvml.nvmlDeviceGetName(h)) or f"GPU {index}"
            result.append({
                "index": index, "nom": name.decode() if isinstance(name, bytes) else str(name),
                "utilisation_pct": util.gpu if util else None,
                "memoire_utilisee_go": round(mem.used / 2**30, 1) if mem else None,
                "memoire_totale_go": round(mem.total / 2**30, 1) if mem else None,
                "temperature_c": read(lambda h=h: nvml.nvmlDeviceGetTemperature(h, nvml.NVML_TEMPERATURE_GPU)),
                "ventilateur_pct": read(lambda h=h: nvml.nvmlDeviceGetFanSpeed(h)),
                "puissance_w": round(power / 1000, 1) if power else None,
                "limite_puissance_w": round(limit / 1000) if limit else None,
                "frequence_gpu_mhz": read(lambda h=h: nvml.nvmlDeviceGetClockInfo(h, nvml.NVML_CLOCK_GRAPHICS)),
                "frequence_memoire_mhz": read(lambda h=h: nvml.nvmlDeviceGetClockInfo(h, nvml.NVML_CLOCK_MEM)),
                "frequence_max_mhz": read(lambda h=h: nvml.nvmlDeviceGetMaxClockInfo(h, nvml.NVML_CLOCK_GRAPHICS)),
                "pilote": read(lambda: nvml.nvmlSystemGetDriverVersion()),
                "pcie": read(lambda h=h: f"PCIe {nvml.nvmlDeviceGetCurrPcieLinkGeneration(h)}.0 "
                                        f"x{nvml.nvmlDeviceGetCurrPcieLinkWidth(h)}"),
            })
        return result
    except Exception:  # noqa: BLE001 — pas de carte NVIDIA ou pilote absent
        return []


# ---------------------------------------------------------------- fiche système (lecture seule, en cache)
INFO_SCRIPT = r"""
$cs = Get-CimInstance Win32_ComputerSystem; $os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor; $bb = Get-CimInstance Win32_BaseBoard; $bios = Get-CimInstance Win32_BIOS
$ram = Get-CimInstance Win32_PhysicalMemory; $vc = Get-CimInstance Win32_VideoController
$pd = Get-PhysicalDisk; $parts = Get-Partition | Where-Object DriveLetter
$dd = Get-CimInstance Win32_DiskDrive
[pscustomobject]@{
 nom = $cs.Name; fabricant = $cs.Manufacturer; modele = $cs.Model; type_systeme = $cs.SystemType
 os = [pscustomobject]@{ nom = $os.Caption; version = $os.Version; build = $os.BuildNumber;
   architecture = $os.OSArchitecture;
   installe = $os.InstallDate.ToString('s'); demarre = $os.LastBootUpTime.ToString('s') }
 cpu = @($cpu | ForEach-Object { [pscustomobject]@{ nom = $_.Name.Trim(); coeurs = $_.NumberOfCores;
   logiques = $_.NumberOfLogicalProcessors;
   base_mhz = $_.MaxClockSpeed; l2_ko = $_.L2CacheSize; l3_ko = $_.L3CacheSize; socket = $_.SocketDesignation;
   virtualisation = $_.VirtualizationFirmwareEnabled } })
 carte_mere = [pscustomobject]@{ fabricant = $bb.Manufacturer; produit = $bb.Product; version = $bb.Version }
 bios = [pscustomobject]@{ version = $bios.SMBIOSBIOSVersion; date = $bios.ReleaseDate.ToString('yyyy-MM-dd');
   fabricant = $bios.Manufacturer }
 memoire = @($ram | ForEach-Object { [pscustomobject]@{ taille_go = [math]::Round($_.Capacity / 1GB);
   vitesse = $_.ConfiguredClockSpeed;
   fabricant = $_.Manufacturer; reference = "$($_.PartNumber)".Trim(); emplacement = $_.DeviceLocator } })
 cartes_graphiques = @($vc | ForEach-Object { [pscustomobject]@{ nom = $_.Name; pilote = $_.DriverVersion } })
 disques = @($pd | ForEach-Object { $n = $_.DeviceId; [pscustomobject]@{ numero = [int]$n; nom = $_.FriendlyName;
   type = "$($_.MediaType)"; bus = "$($_.BusType)"; taille_go = [math]::Round($_.Size / 1GB);
   sante = "$($_.HealthStatus)";
   lecteurs = @($parts | Where-Object DiskNumber -eq ([int]$n) | ForEach-Object { "$($_.DriveLetter):" }) } })
 modeles_disques = @($dd | ForEach-Object { [pscustomobject]@{ index = $_.Index; modele = $_.Model } })
} | ConvertTo-Json -Depth 5 -Compress
"""

DEVICES_SCRIPT = r"""
$classes = @('%s')
Get-PnpDevice -PresentOnly | Where-Object { $classes -contains $_.Class } |
  Select-Object FriendlyName, Class, Status | ConvertTo-Json -Depth 2 -Compress
"""


class SystemInfo:
    """Fiche système et périphériques (requêtes lentes : en cache)."""

    def __init__(self, runner: Callable[[str, float], Any] = _ps, ttl_s: float = 600.0) -> None:
        self.runner, self.ttl_s = runner, ttl_s
        self._cache: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def _cached(self, key: str, build: Callable[[], Any], refresh: bool) -> Any:
        with self._lock:
            hit = self._cache.get(key)
            if hit and not refresh and time.monotonic() - hit[0] < self.ttl_s:
                return hit[1]
        value = build()
        with self._lock:
            self._cache[key] = (time.monotonic(), value)
        return value

    def info(self, refresh: bool = False) -> dict[str, Any]:
        return self._cached("info", self._build_info, refresh)

    def _build_info(self) -> dict[str, Any]:
        raw = self.runner(INFO_SCRIPT, 40.0) or {}
        if not isinstance(raw, dict):
            raw = {}
        ram = _list(raw.get("memoire"))
        disks = _list(raw.get("disques"))
        gpus = nvml_details()
        info = {**raw, "cpu": _list(raw.get("cpu")), "memoire": ram, "disques": disks, "volumes": volumes(disks),
                "cartes_graphiques": _list(raw.get("cartes_graphiques"))}
        info["resume"] = {
            "memoire_go": sum(m.get("taille_go") or 0 for m in ram) or round(psutil.virtual_memory().total / 2**30),
            "memoire_mhz": max((m.get("vitesse") or 0 for m in ram), default=0) or None,
            "processeur": (info["cpu"][0].get("nom") if info["cpu"] else "") or "",
            "processeur_ghz": round((info["cpu"][0].get("base_mhz") or 0) / 1000, 2) if info["cpu"] else None,
            "vram_go": round(sum(g.get("memoire_totale_go") or 0 for g in gpus)) if gpus else None,
            "nb_gpus": len(gpus) or len(info["cartes_graphiques"]),
            "stockage_go": sum(d.get("taille_go") or 0 for d in disks),
            "stockage_utilise_go": round(sum(v["utilise_go"] for v in info["volumes"])),
        }
        info["complet"] = bool(raw)
        return info

    def devices(self, refresh: bool = False) -> dict[str, Any]:
        return self._cached("devices", self._build_devices, refresh)

    def _build_devices(self) -> dict[str, Any]:
        raw = _list(self.runner(DEVICES_SCRIPT % "','".join(PERIPHERAL_CLASSES), 40.0))
        groups: dict[str, list[dict[str, str]]] = {}
        seen: set[tuple[str, str]] = set()
        for item in raw:
            if not isinstance(item, dict) or not item.get("FriendlyName"):
                continue
            name, cls = str(item["FriendlyName"]), str(item.get("Class", ""))
            group = PERIPHERAL_CLASSES.get(cls, "Autres")
            if cls == "HIDClass" and not GAMEPAD.search(name):
                continue  # périphériques HID internes : seulement les manettes
            if cls == "Net" and VIRTUAL_NET.search(name):
                continue
            if (group, name) in seen:
                continue
            seen.add((group, name))
            groups.setdefault(group, []).append({"nom": name, "etat": "ok" if item.get("Status") == "OK" else
                                                 str(item.get("Status") or "inconnu").lower()})
        return {"groupes": [{"nom": g, "appareils": sorted(v, key=lambda d: d["nom"].lower())}
                            for g, v in sorted(groups.items())], "complet": bool(raw)}


def volume_label(root: str) -> str:
    buf = ctypes.create_unicode_buffer(261)
    try:
        ok = ctypes.windll.kernel32.GetVolumeInformationW(root, buf, 261, None, None, None, None, 0)
    except (AttributeError, OSError):
        return ""
    return buf.value if ok else ""


def volumes(disks: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Lecteurs comme dans « Ce PC » : nom, lettre, espace libre, disque physique."""
    owner = {letter.upper(): d for d in (disks or []) for letter in _list(d.get("lecteurs"))}
    result = []
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.fstype:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        letter = part.device.rstrip("\\").upper()
        disk = owner.get(letter, {})
        result.append({"lecteur": letter, "nom": volume_label(part.mountpoint) or "Disque local",
                       "systeme_fichiers": part.fstype, "total_go": round(usage.total / 2**30, 1),
                       "libre_go": round(usage.free / 2**30, 1), "utilise_go": round(usage.used / 2**30, 1),
                       "pct": usage.percent, "disque": disk.get("nom", ""), "disque_numero": disk.get("numero")})
    return result


# ---------------------------------------------------------------- Inoue : processus gourmands, alimentation
def heavy_processes(limit: int = 15, interval: float = 0.5) -> list[dict[str, Any]]:
    """Processus les plus gourmands (processeur et mémoire), sans les processus système."""
    me = os.getpid()
    procs = []
    for proc in psutil.process_iter(["pid", "name", "memory_info", "username"]):
        if proc.pid in (0, 4):  # « processus inactif » et noyau : ne sont pas des programmes
            continue
        try:
            proc.cpu_percent(None)
            procs.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    time.sleep(interval)
    cores = psutil.cpu_count() or 1
    rows = []
    for proc in procs:
        try:
            cpu = proc.cpu_percent(None) / cores
            name = proc.info.get("name") or ""
            mem = proc.info.get("memory_info")
            rows.append({"pid": proc.pid, "nom": name, "cpu_pct": round(cpu, 1),
                         "memoire_mo": round(mem.rss / 2**20) if mem else 0,
                         "protege": name.lower() in PROTECTED or proc.pid in (me, 0, 4)
                         or not proc.info.get("username")})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    rows.sort(key=lambda r: (r["cpu_pct"] * 50 + r["memoire_mo"] / 20), reverse=True)
    return rows[:limit]


def stop_process(pid: int, name: str) -> dict[str, Any]:
    """Ferme un processus sur demande (clic), si son nom correspond toujours et s'il n'est pas protégé."""
    try:
        proc = psutil.Process(int(pid))
        actual = proc.name()
    except (psutil.NoSuchProcess, ValueError) as exc:
        raise ValueError("processus introuvable (déjà fermé ?)") from exc
    if actual.lower() != str(name).lower():
        raise ValueError("ce numéro de processus correspond maintenant à un autre programme")
    if actual.lower() in PROTECTED or proc.pid in (os.getpid(), 0, 4):
        raise ValueError(f"{actual} est un processus système ou du Hub : il n'est jamais fermé")
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except psutil.TimeoutExpired:
        return {"ferme": False, "detail": f"{actual} n'a pas répondu dans les 5 s (il se ferme peut-être encore)"}
    except psutil.AccessDenied as exc:
        raise ValueError(f"Windows refuse de fermer {actual} (droits administrateur)") from exc
    return {"ferme": True, "detail": f"{actual} fermé"}


POWER_LINE = re.compile(r"GUID[^:]*:\s*([0-9a-f-]{36})\s+\((.+?)\)\s*(\*)?", re.I)


def power_plans(runner: Callable[..., Any] = subprocess.run) -> list[dict[str, Any]]:
    try:
        out = runner(["powercfg", "/list"], capture_output=True, timeout=10, creationflags=NO_WINDOW)
        text = out.stdout.decode("cp850", "replace") if isinstance(out.stdout, bytes) else str(out.stdout)
    except (OSError, subprocess.SubprocessError):
        return []
    return [{"guid": m.group(1).lower(), "nom": m.group(2).strip(), "actif": bool(m.group(3))}
            for m in POWER_LINE.finditer(text)]


def set_power_plan(guid: str, runner: Callable[..., Any] = subprocess.run) -> list[dict[str, Any]]:
    plans = power_plans(runner)
    if guid.lower() not in {p["guid"] for p in plans}:
        raise ValueError("mode d'alimentation inconnu")
    runner(["powercfg", "/setactive", guid.lower()], capture_output=True, timeout=10, creationflags=NO_WINDOW)
    return power_plans(runner)


# ---------------------------------------------------------------- fenêtres de Windows et outils
def open_windows(target: str, drive: str = "", starter: Callable[[str], Any] | None = None) -> str:
    starter = starter or os.startfile  # type: ignore[attr-defined]
    if target == "lecteur":
        if not re.fullmatch(r"[A-Za-z]:", drive or ""):
            raise ValueError("lecteur invalide")
        starter(drive.upper() + "\\")
        return f"Explorateur sur {drive.upper()}"
    if target not in WINDOWS_TARGETS:
        raise ValueError("fenêtre inconnue")
    label, command = WINDOWS_TARGETS[target]
    starter(command)
    return label


def tools_state() -> list[dict[str, Any]]:
    running = {(p.info.get("name") or "").lower() for p in psutil.process_iter(["name"])}
    result = []
    for key, tool in TOOLS.items():
        path = next((p for p in tool.get("paths", []) if Path(p).is_file()), "")
        installed = bool(path) or (bool(tool.get("appx")) and appx_installed(tool["appx"].split("!")[0]))
        result.append({"id": key, "nom": tool["nom"], "role": tool["role"], "installe": installed,
                       "en_cours": tool.get("process", "").lower() in running,
                       "telecharger": tool.get("telecharger", "")})
    return result


def appx_installed(family: str) -> bool:
    packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Packages" / family
    return packages.is_dir()


def launch_tool(key: str, starter: Callable[[str], Any] | None = None) -> str:
    starter = starter or os.startfile  # type: ignore[attr-defined]
    tool = TOOLS.get(key)
    if not tool:
        raise ValueError("outil inconnu")
    path = next((p for p in tool.get("paths", []) if Path(p).is_file()), "")
    if path:
        starter(path)  # Windows demande l'autorisation si l'outil exige des droits administrateur
    elif tool.get("appx") and appx_installed(tool["appx"].split("!")[0]):
        starter(f"shell:AppsFolder\\{tool['appx']}")
    else:
        raise ValueError(f"{tool['nom']} n'est pas installé dans son dossier par défaut")
    return tool["nom"]


# ---------------------------------------------------------------- capteurs : LibreHardwareMonitor (facultatif)
SENSOR_KINDS = {"Temperature": "temperatures", "Fan": "ventilateurs", "Voltage": "tensions", "Clock": "frequences",
                "Load": "utilisation", "Power": "puissances", "Control": "commandes", "Flow": "debits"}
UNIT_KIND = {"°C": "temperatures", "RPM": "ventilateurs", "V": "tensions", "MHz": "frequences", "%": "utilisation",
             "W": "puissances", "L/h": "debits"}


def lhm_sensors(url: str = "http://127.0.0.1:8085/data.json", timeout: float = 2.0) -> dict[str, Any]:
    """Capteurs de LibreHardwareMonitor (serveur web local activé). Vide s'il ne tourne pas."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 — adresse locale fixe
            tree = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return {"disponible": False}
    groups: dict[str, list[dict[str, Any]]] = {kind: [] for kind in SENSOR_KINDS.values()}

    def walk(node: dict[str, Any], path: list[str]) -> None:
        children = node.get("Children") or []
        value = str(node.get("Value") or "")
        if not children and node.get("SensorId") and value:
            kind = SENSOR_KINDS.get(str(node.get("Type", ""))) or next(
                (k for unit, k in UNIT_KIND.items() if value.endswith(unit)), "")
            number = re.match(r"-?[\d.,]+", value.replace("\u202f", "").replace(" ", ""))
            if kind:
                groups[kind].append({"nom": str(node.get("Text", "")), "materiel": " › ".join(path[-2:]),
                                     "valeur": value, "nombre": float(number.group().replace(",", "."))
                                     if number else None})
        for child in children:
            walk(child, [*path, str(node.get("Text", ""))] if node.get("Text") else path)

    walk(tree, [])
    fans = groups["ventilateurs"]
    return {"disponible": True, **groups,
            "pompe": [f for f in fans if re.search(r"pump|pompe|aio", f["nom"], re.I)],
            "ventilateurs_actifs": [f for f in fans if (f["nombre"] or 0) > 0]}


# ---------------------------------------------------------------- courbes de ventilateurs du BIOS (administrateur)
FAN_PROBE = Path(__file__).with_name("asus_fan_probe.ps1")


def read_bios_fans(out: Path) -> dict[str, Any]:
    """Lance la lecture des courbes du BIOS avec élévation (Windows demande l'autorisation). Lecture seule."""
    out.parent.mkdir(parents=True, exist_ok=True)
    args = f"-NoProfile -ExecutionPolicy Bypass -File \"{FAN_PROBE}\" -Out \"{out}\""
    ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe", args, None, 0)
    return {"demande": True, "fichier": out.name}


def bios_fans(out: Path) -> dict[str, Any] | None:
    try:
        return json.loads(out.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
