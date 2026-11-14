# Regras para assistentes de IA (Claude, ChatGPT, Codex) neste projeto

1. **Git antes de mexer:** confira `git status`; faça commit do estado atual antes de qualquer reorganização.
2. **Fase 1 intacta:** não altere nada em `fase1_extrator\` (repositório do Filipe, segunda versão da pipeline).
3. **Não apague** dados, `.gz`, CSV, `cache\`, `.venv\` ou `dados\` sem aprovação explícita do Katsu.
4. **Limite 1.000** em fluxos de teste. Nunca inicie fluxo de 1 milhão sem pedido explícito (ocupa >20 GB).
5. **Alvo científico:** o modelo principal é o **EC 1 a EC 7** (sete classes enzimáticas); EC 2 × EC 3 é complementar e a regra dos nove aminoácidos é só prova de conceito. Níveis finos da hierarquia EC, classe "não enzima", calibração e análise dentro dos grupos são trabalho futuro — não implementar sem pedido.
6. **Reprodutibilidade:** ESM-2 `facebook/esm2_t6_8M_UR50D` na revisão `c731040f…`; semente 42; partições por grupo MMseqs2 (SHA256); parâmetros do `easy-linclust` fixos em código. Não troque modelo, revisão, semente ou parâmetros.
7. **Plataforma:** o sistema mira só Windows (MMseqs2 nativo ou WSL). Portabilidade para Linux/macOS/contêiner é trabalho futuro.
8. **Testes:** rode `.venv\Scripts\python.exe -m unittest discover -s testes` com `TEMP` dentro de `C:\ai_tcc` antes de cada commit.
9. **Ajustes por computador** vão em `config_local.json` (tela Configurações), não no `sistema_tcc\config.json`.
