# Comece aqui — execução local

## 1. Abrir o dashboard

```powershell
cd C:\ai_tcc
.\.venv\Scripts\python.exe -m sistema_tcc --abrir
```

Ou abra `iniciar_sistema.cmd`. A página é [http://127.0.0.1:8765](http://127.0.0.1:8765). Os resultados anteriores aparecem como importados. Abrir o painel não cria automaticamente outro experimento completo.

## 2. Rodar tudo automaticamente

```powershell
cd C:\ai_tcc
.\.venv\Scripts\python.exe -m sistema_tcc --abrir --novo-fluxo --limite 1000
```

Ou abra **`iniciar_fluxo_completo.cmd`**. Use esse comando uma vez para cada experimento novo. Se o servidor v2 já estiver aberto, o comando enfileira a nova execução nele.

O fluxo executa entrada → MMseqs2 inicial → rótulos → embeddings → auditoria → consolidação → agrupamento global → partições → treino → registro no banco.

1.000 é o máximo de candidatos únicos elegíveis antes do MMseqs2. O número de embeddings corresponde aos representantes recuperados e pode ser menor. Uma fonte com poucos registros ou sem as duas classes pode não permitir o treino; nesse caso, escolha mais fontes ou um limite maior.

## 3. Escolher um GZ no painel

Em **Pipeline automático → Novo experimento completo**, escolha a fonte e o limite. Membros `.gz` dentro de ZIP também são listados. Clique em **Iniciar fluxo completo**. Os CSV antigos não são necessários para essa execução nova.

## 4. Acompanhar a execução

Selecione seu experimento no topo. Em **Tarefas e logs**, abra a tarefa de fluxo completo. O navegador consulta as atualizações a cada 2 segundos; os logs completos ficam em `dados/execucoes_tcc/IDENTIFICADOR/logs/`.

Em **Banco**, procure o acesso NCBI ou UID. **Usar sequência** preenche a consulta. Representantes recebem embeddings e partições; os demais candidatos conservam a origem, sequência e grupo inicial no SQLite.

## 5. Consultar depois do treino

Na aba de consulta, informe de 1 a 512 resíduos. O modelo da execução selecionada precisa estar concluído. A tela compara a regra direta com a previsão do MLP e seus escores softmax sem calibração.

## 6. Pausar ou encerrar

**Pausar fila** deixa a fase ativa terminar e interrompe antes da seguinte. **Retomar execução** reutiliza fases confirmadas após conferir hashes. **Encerrar sistema**, no rodapé, espera a fase ativa e encerra o serviço.

Durante embeddings, a pausa entre fases aguarda o gerador concluir o recorte. A retomada dos lotes existentes é mantida, mas não há retomada do otimizador no meio do treino. Mais detalhes em [docs/OPERACAO.md](OPERACAO.md).
