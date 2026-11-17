# Tâches courantes pour l'agent local

Liste lue par `scripts/relay_orchestrator.py` et donnée à l'agent local à chaque bascule.
L'agent cloud la met à jour avant chaque fin de session. Détail : `AGENT_HANDOFF.md`, « Prochaines tâches ».

- [x] `core/hardware/gpu_monitor.py`, `core/module_api.py`, `core/guardians/inoue.py`, `core/guardians/fuma.py` (faits le 16/11/2026).
- [x] `core/bus.py`, `core/module_runner.py`, `core/scheduler.py`, `core/daemon.py`, `core/api.py` (faits le 16/11/2026). Le jalon J2 est terminé.
- [x] Jalon J3 : `modules/gaming_hud/` (application, adaptateurs, module, manifeste) et `core/llm_router.py` (faits le 17/11/2026).
- [ ] 1. `assets/logo_if_core.svg` et `assets/logo_if_core_mono.svg` — Yin & Yang géométrique simple (cercles et arcs), Inoue claire, Fuma sombre. SVG écrit à la main, moins de 60 lignes, sans image embarquée. Test : le fichier est du XML valide (`xml.etree.ElementTree`).
- [ ] 2. `modules/gaming_hud/web/obs_hud.html` — page à fond transparent, sans dépendance externe, qui affiche un objet JSON reçu par `EventSource("/obs-hud/events")` : nom, niveau, zone, liste des GPU. Pas de serveur dans cette tâche.
- [ ] 3. `tests/gaming_hud/test_obs_hud_page.py` — vérifie que la page ne référence aucune adresse `http://` ou `https://` externe et ne contient aucun `<script src=` distant.

Ne modifie rien dans `modules/gaming_hud/app/` : c'est le code d'origine.
