# Tâches courantes pour l'agent local

Liste lue par `scripts/relay_orchestrator.py` et donnée à l'agent local à chaque bascule.
L'agent cloud la met à jour avant chaque fin de session. Détail : `AGENT_HANDOFF.md`, « Prochaines tâches ».

- [x] `core/hardware/gpu_monitor.py`, `core/module_api.py`, `core/guardians/inoue.py`, `core/guardians/fuma.py` (faits le 16/11/2026).
- [ ] 1. `core/bus.py` + `tests/core/test_bus.py` — publication / abonnement entre processus sur `127.0.0.1`. Utilise `Event` de `core/module_api.py`. Un test envoie un événement d'un processus à un autre.
- [ ] 2. `core/scheduler.py` + `tests/core/test_scheduler.py` — file d'attente GPU unique. Demande l'accord d'Inoue (`Inoue.request`) avant chaque tâche, appelle `Inoue.release` après.
- [ ] 3. `core/daemon.py` + `tests/core/test_daemon.py` — découvre les modules (`discover_manifests`), démarre sans GPU, charge et décharge un module de test dans un processus séparé, le fait surveiller par `Fuma`.
