"""État du PC (Accueil, Inoue) : listes fermées, lecture seule, refus des actions dangereuses."""
from __future__ import annotations

import io
import json
import os
from types import SimpleNamespace
from typing import Any

import pytest

from core.hardware import system_info as si
from tests.core.test_dashboard import client  # noqa: F401 — fixture partagée

GUID = "GUID du mode de gestion de l'alimentation : "
POWERCFG = ("Jeux de paramètres de gestion de l'alimentation existants (* Actif)\r\n"
            "-----------------------------------\r\n"
            f"{GUID}381b4222-f694-41f0-9685-ff5bb260df2e  (Utilisation normale) *\r\n"
            f"{GUID}8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c  (Performances élevées)\r\n"
            f"{GUID}a1841308-3541-4fab-bc81-f71556f20b4a  (Économie d'énergie)\r\n")


def fake_powercfg(calls: list[list[str]]) -> Any:
    def run(cmd: list[str], **_: Any) -> SimpleNamespace:
        calls.append(cmd)
        return SimpleNamespace(stdout=POWERCFG.encode("cp850"))
    return run


def test_power_plans_are_parsed_and_only_known_ones_applied() -> None:
    calls: list[list[str]] = []
    plans = si.power_plans(fake_powercfg(calls))
    assert [p["nom"] for p in plans] == ["Utilisation normale", "Performances élevées", "Économie d'énergie"]
    assert [p["actif"] for p in plans] == [True, False, False]
    with pytest.raises(ValueError, match="inconnu"):
        si.set_power_plan("00000000-0000-0000-0000-000000000000", fake_powercfg(calls))
    assert not any("/setactive" in c for c in calls)
    si.set_power_plan("8C5E7FDA-E8BF-4A96-9A85-A6E23A8C635C", fake_powercfg(calls))
    assert ["powercfg", "/setactive", "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"] in calls


def test_windows_and_tools_come_from_closed_lists() -> None:
    opened: list[str] = []
    assert si.open_windows("gestion_disques", starter=opened.append) == "Gestion des disques"
    assert si.open_windows("lecteur", "e:", starter=opened.append) == "Explorateur sur E:"
    assert opened == ["diskmgmt.msc", "E:\\"]
    for target, drive in (("cmd.exe", ""), ("lecteur", "C:\\Windows"), ("lecteur", "..")):
        with pytest.raises(ValueError):
            si.open_windows(target, drive, starter=opened.append)
    with pytest.raises(ValueError, match="inconnu"):
        si.launch_tool("powershell", starter=opened.append)
    assert len(opened) == 2


def test_stop_process_refuses_the_hub_and_renamed_pids() -> None:
    me = si.psutil.Process(os.getpid()).name()
    with pytest.raises(ValueError, match="jamais fermé"):
        si.stop_process(os.getpid(), me)
    with pytest.raises(ValueError, match="autre programme"):
        si.stop_process(os.getpid(), "pas-le-bon.exe")
    with pytest.raises(ValueError, match="introuvable"):
        si.stop_process(0x7FFFFFF0, "x.exe")
    assert "svchost.exe" in si.PROTECTED and "explorer.exe" in si.PROTECTED


def test_system_info_summary_and_device_groups() -> None:
    raw = {"nom": "PC", "cpu": {"nom": "Intel Core i7-8700K", "base_mhz": 3700, "coeurs": 6, "logiques": 12},
           "memoire": [{"taille_go": 8, "vitesse": 3200}] * 4,
           "disques": [{"numero": 0, "nom": "SSD", "taille_go": 932},
                       {"numero": 1, "nom": "NVMe", "taille_go": 466}],
           "cartes_graphiques": {"nom": "GPU"}}
    devices = [{"FriendlyName": "Clavier HID", "Class": "Keyboard", "Status": "OK"},
               {"FriendlyName": "Périphérique HID interne", "Class": "HIDClass", "Status": "OK"},
               {"FriendlyName": "Xbox Wireless Controller", "Class": "HIDClass", "Status": "OK"},
               {"FriendlyName": "WAN Miniport (IP)", "Class": "Net", "Status": "OK"},
               {"FriendlyName": "Clavier HID", "Class": "Keyboard", "Status": "OK"},
               {"FriendlyName": "Casque", "Class": "AudioEndpoint", "Status": "Unknown"}]

    def runner(script: str, timeout: float) -> Any:
        return devices if "Get-PnpDevice" in script else raw

    info = si.SystemInfo(runner).info()
    resume = info["resume"]
    assert resume["memoire_go"] == 32 and resume["memoire_mhz"] == 3200 and resume["processeur_ghz"] == 3.7
    assert resume["stockage_go"] == 932 + 466 and info["cpu"][0]["coeurs"] == 6
    groups = {g["nom"]: g["appareils"] for g in si.SystemInfo(runner).devices()["groupes"]}
    assert groups["Claviers"] == [{"nom": "Clavier HID", "etat": "ok"}]  # doublon retiré
    assert [d["nom"] for d in groups["Manettes"]] == ["Xbox Wireless Controller"]  # HID internes écartés
    assert "Réseau" not in groups and groups["Audio"][0]["etat"] == "unknown"


def test_lhm_sensors_are_grouped_and_pump_found(monkeypatch: pytest.MonkeyPatch) -> None:
    def sensor(text: str, kind: str, value: str) -> dict[str, Any]:
        return {"Text": text, "Type": kind, "Value": value, "SensorId": f"/x/{text}", "Children": []}
    tree = {"Text": "Sensor", "Children": [{"Text": "DESKTOP", "Children": [
        {"Text": "ROG MAXIMUS XI HERO", "Children": [
        {"Text": "Nuvoton NCT6798D", "Children": [
            sensor("CPU", "Temperature", "41,0 °C"), sensor("CPU Fan", "Fan", "1 210 RPM"),
            sensor("W_PUMP+", "Fan", "2 850 RPM"), sensor("Chassis Fan #3", "Fan", "0 RPM"),
            sensor("Vcore", "Voltage", "1,232 V")]}]}]}]}
    monkeypatch.setattr(si.urllib.request, "urlopen",
                        lambda url, timeout: io.BytesIO(json.dumps(tree).encode("utf-8")))
    data = si.lhm_sensors()
    assert data["disponible"] and data["temperatures"][0]["nombre"] == 41.0
    assert [f["nom"] for f in data["pompe"]] == ["W_PUMP+"] and data["pompe"][0]["nombre"] == 2850.0
    assert [f["nom"] for f in data["ventilateurs_actifs"]] == ["CPU Fan", "W_PUMP+"]
    assert data["tensions"][0]["materiel"] == "ROG MAXIMUS XI HERO › Nuvoton NCT6798D"

    def refused(url: str, timeout: float) -> Any:
        raise si.urllib.error.URLError("refusé")
    monkeypatch.setattr(si.urllib.request, "urlopen", refused)
    assert si.lhm_sensors() == {"disponible": False}


def test_fan_probe_only_reads() -> None:
    probe = si.FAN_PROBE.read_text(encoding="utf-8")
    assert "GetFanPolicy" in probe and "GetManualFanCurve" in probe
    calls = [line for line in probe.splitlines() if "-MethodName" in line]
    assert calls and all("-MethodName Get" in line for line in calls)  # aucune méthode Set* appelée
    assert "ASUSHW" not in probe


def test_system_routes(client) -> None:  # noqa: F811
    live = client.get("/system/live").json()
    assert {"cpu", "memoire", "historique"} <= set(live)
    assert client.post("/system/open", json={"cible": "regedit"},
                       headers={"Origin": "http://127.0.0.1:5750"}).status_code == 400
    assert client.post("/system/tools/launch", json={"outil": "cmd"},
                       headers={"Origin": "http://127.0.0.1:5750"}).status_code == 400
    assert client.post("/system/process/stop", json={"pid": os.getpid(), "nom": "autre.exe"},
                       headers={"Origin": "http://127.0.0.1:5750"}).status_code == 400
    foreign = {"Origin": "https://exemple.org"}
    assert client.post("/system/open", json={"cible": "ce_pc"}, headers=foreign).status_code == 403
    tools = client.get("/system/tools").json()
    assert {t["id"] for t in tools} >= {"armoury_crate", "gpu_tweak", "gpu_z", "cpu_z"}
