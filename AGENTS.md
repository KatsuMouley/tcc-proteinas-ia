# Regras para assistentes de IA (Claude, ChatGPT, Codex) neste projeto

1. **Git antes de mexer:** confira `git status`; faça commit do estado atual antes de qualquer reorganização.
2. **Fase 1 intacta:** não altere nada em `fase1_extrator\` (repositório do Filipe).
3. **Não apague** dados, `.gz`, CSV, `cache\`, `.venv\` ou `dados\` sem aprovação explícita do Katsu.
4. **Limite 1.000** em fluxos de teste. Nunca inicie fluxo de 1 milhão sem pedido explícito (ocupa >20 GB).
5. **Alvo científico:** EC 2 (Transferase) × EC 3 (Hidrolase). As 7 classes EC e a análise dentro dos grupos são só trabalho futuro — não implementar.
6. **Reprodutibilidade:** ESM-2 `facebook/esm2_t6_8M_UR50D` na revisão `c731040f…`; semente 42; partições por grupo MMseqs2 (SHA256). Não troque modelo, revisão ou semente.
7. **Testes:** rode `.venv\Scripts\python.exe -m unittest discover -s testes` com `TEMP` dentro de `C:\ai_tcc` antes de cada commit.
8. **Ajustes por computador** vão em `config_local.json` (tela Configurações), não no `sistema_tcc\config.json`.
