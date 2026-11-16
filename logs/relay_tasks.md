# Tâches courantes pour l'agent local

Liste lue par `scripts/relay_orchestrator.py` et donnée à l'agent local à chaque bascule.
L'agent cloud la met à jour avant chaque fin de session. Détail : `AGENT_HANDOFF.md`, « Prochaines tâches ».

- [ ] 1. `core/hardware/gpu_monitor.py` + `tests/core/test_gpu_monitor.py` — backend `pynvml`, repli « inconnu », aucune exception sans GPU.
- [ ] 2. `core/module_api.py` + `tests/core/test_module_api.py` — classe de base de module, validation de `manifest.json`.
- [ ] 3. `core/guardians/inoue.py` + `tests/core/test_inoue.py` — budget VRAM avec marge de 10 %, moniteur GPU factice.
- [ ] 4. `core/guardians/fuma.py` + `tests/core/test_fuma.py` — watchdog et mode nocturne, horloge injectée.
