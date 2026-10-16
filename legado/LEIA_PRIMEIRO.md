# Projeto completo e organizado — proteínas / TCC

Este pacote reúne o dashboard e controlador v2, os quatro scripts científicos, o piloto que eles importam, as ferramentas de diagnóstico, testes e documentação. Os arquivos recebidos de versões antigas estão guardados como referência.

## Aplicar no seu projeto existente

1. No dashboard aberto, clique em **Encerrar sistema**. Aguarde a fase ativa terminar e o terminal encerrar. Outros scripts Python desse projeto também precisam estar encerrados.
2. Extraia este ZIP em uma pasta fora de `C:\ai_tcc`, por exemplo em Downloads. Mantenha juntos `APLICAR_NO_PROJETO.cmd`, `atualizar_projeto.py` e a pasta `projeto`.
3. Dê dois cliques em **APLICAR_NO_PROJETO.cmd**. Ele usa o Python que já existe em `C:\ai_tcc\.venv`.
4. Confira o resultado `"ok": true` e o caminho do backup informado.
5. Abra `C:\ai_tcc\iniciar_sistema.cmd` para acessar o dashboard. Para iniciar uma execução nova desde os GZ até o treinamento e banco, abra **`C:\ai_tcc\iniciar_fluxo_completo.cmd`**.

O segundo inicializador já cria e enfileira um experimento novo, com até 1.000 candidatos antes do agrupamento. Ao terminar, o fluxo encerra aquela execução. Para outra, use o painel; abrir esse inicializador novamente cria outro experimento.

Dashboard: [http://127.0.0.1:8765](http://127.0.0.1:8765).

O atualizador confere os hashes do pacote, faz backup antes de substituir código e arquiva apenas nomes conhecidos de arquivos antigos na raiz. Ele mantém configurações existentes e arquivos desconhecidos. `.venv`, `cache`, `arquivos .gz`, `arquivos csv` e resultados em `dados` continuam no lugar. A atualização usa o arquivo de bloqueio da fila para impedir alteração com o dashboard ativo.

Não é necessário executar os antigos instaladores CPU/GPU. Este pacote não instala bibliotecas e não inclui os dados, pesos dos modelos ou a `.venv`: ele reutiliza o que você já tem no PC.

## Usar outro caminho

No PowerShell, dentro da pasta extraída:

```powershell
.\APLICAR_NO_PROJETO.cmd "D:\ai_tcc"
```

O projeto nesse caminho já precisa ter seu próprio ambiente Python preparado. Ambientes virtuais não devem ser transportados entre computadores como se fossem bibliotecas instaláveis.

## Ver as mudanças sem aplicar

Ainda dentro da pasta extraída:

```powershell
& "C:\ai_tcc\.venv\Scripts\python.exe" .\atualizar_projeto.py --destino "C:\ai_tcc" --simular
```

## Restaurar o código anterior

Encerre o dashboard. Use o caminho exato do backup mostrado pelo atualizador:

```powershell
& "C:\ai_tcc\.venv\Scripts\python.exe" .\atualizar_projeto.py --destino "C:\ai_tcc" --restaurar "C:\ai_tcc\historico\atualizacoes\NOME_DO_BACKUP"
```

A restauração confere o backup e interrompe se houver edição posterior de um arquivo que seria substituído. O backup inclui `plano.json` e os arquivos anteriores em `arquivos/`. Ele continua disponível depois da restauração.

## Documentação e verificações

Depois da aplicação, leia `C:\ai_tcc\README.md` e `C:\ai_tcc\COMECE_AQUI_SISTEMA.md`. A arquitetura, o mapa de arquivos, as dependências e o histórico estão em `docs/` e podem ser abertos no Obsidian.

Os testes do projeto e do atualizador usam diretórios temporários. GPU, ESM-2, MMseqs2 e treinamento reais precisam ser verificados no seu Windows/WSL. Os testes locais não substituem essa execução.

Para conferir o próprio atualizador sem aplicar uma atualização:

```powershell
& "C:\ai_tcc\.venv\Scripts\python.exe" -m unittest discover -s .\testes_atualizacao -p "test*.py" -v
```
