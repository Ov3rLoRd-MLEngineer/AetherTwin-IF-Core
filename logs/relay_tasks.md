# Tâches courantes pour l'agent local

Liste lue par `scripts/relay_orchestrator.py` et donnée à l'agent local à chaque bascule.
L'agent cloud la met à jour avant chaque fin de session. Détail : `AGENT_HANDOFF.md`, « Prochaines tâches ».

- [x] `core/hardware/gpu_monitor.py`, `core/module_api.py`, `core/guardians/inoue.py`, `core/guardians/fuma.py` (faits le 16/11/2026).
- [x] `core/bus.py`, `core/module_runner.py`, `core/scheduler.py`, `core/daemon.py`, `core/api.py` (faits le 16/11/2026). Le jalon J2 est terminé.
- [x] Jalon J3 : `modules/gaming_hud/` (application, adaptateurs, module, manifeste) et `core/llm_router.py` (faits le 17/11/2026).
- [x] Jalon J4 : overlay OBS, logo, tests de rendu (faits le 17/11/2026).
- [ ] 1. `modules/genesis_lab/bio.py` + `tests/genesis_lab/test_bio.py` — fonctions pures, sans dépendance : `parse_fasta(texte) -> list[(nom, séquence)]`, `gc_percent(seq)`, `reverse_complement(seq)`, `translate(seq)` avec le code génétique standard. Valeurs de référence dans les tests : `gc_percent("ATGC") == 50.0`, `translate("ATGGCCTAA") == "MA*"`.
- [ ] 2. `modules/genesis_lab/astro.py` + test — `orbital_period_s(demi_grand_axe_m, masse_centrale_kg)` (3ᵉ loi de Kepler), `absolute_magnitude(m, distance_pc)`. Référence : la période de la Terre vaut 365,25 jours à 0,1 % près.
- [ ] 3. `modules/genesis_lab/chem.py` + test — `molar_mass(formule)` pour des formules simples (`H2O`, `CO2`, `C6H12O6`). Référence : `molar_mass("H2O")` vaut 18,015 g/mol à 0,01 près.

Les calculs sont du code déterministe : n'appelle jamais un LLM pour obtenir un nombre.

Ne modifie rien dans `modules/gaming_hud/app/` : c'est le code d'origine.
