# Tâches courantes pour l'agent local

Liste lue par `scripts/relay_orchestrator.py` et donnée à l'agent local à chaque bascule.
L'agent cloud la met à jour avant chaque fin de session. Détail : `AGENT_HANDOFF.md`, « Prochaines tâches ».

- [x] `core/hardware/gpu_monitor.py`, `core/module_api.py`, `core/guardians/inoue.py`, `core/guardians/fuma.py` (faits le 16/11/2026).
- [x] `core/bus.py`, `core/module_runner.py`, `core/scheduler.py`, `core/daemon.py`, `core/api.py` (faits le 16/11/2026). Le jalon J2 est terminé.
- [ ] 1. `modules/gaming_hud/adapters/base.py` + `tests/gaming_hud/test_adapter_base.py` — protocole `GameAdapter` : `id`, `detect()`, `read_state()`, `schema()`, `widgets()`, `privacy_filter(state, mode)`, `context_for_llm(state)`. Aucun import de pygame dans ce fichier.
- [ ] 2. `modules/gaming_hud/adapters/log_tail.py` + test — suit un fichier texte ; les règles regex viennent d'un YAML ; `read_state()` rend un dictionnaire. Test avec un fichier temporaire, sans jeu.
- [ ] 3. `modules/gaming_hud/manifest.json` — `name: gaming_hud`, `entry`, `vram_min_gb: 0`, déclencheurs `Wow.exe` et `obs64.exe`. Vérifie avec `core.module_api.load_manifest`.

Ne porte pas `ui.py` (93 Ko) : cette tâche est réservée à l'agent cloud.
