# Piloto EC 2 × EC 3 — etapa 2: cobertura de anotações

Projeto: Inteligência Artificial Aplicada à Genética e Bioinformática  
Preparação do pacote: 13/10/2026, America/Sao_Paulo

**Revisão 2 — correção da integração observada no PC.** O cliente anterior
ignorava `suggestedIds`. O retorno real continha 176 registros em `results`,
15 IDs em `failedIds` e 309 pares em `suggestedIds`, com destinos `UPI...`.
Isso bloqueava a contabilização antes da análise EC. A revisão 2 registra
as sugestões UniParc separadamente e mantém todos os critérios de aceitação
de rótulos. Esses números descrevem a resposta da API, não a quantidade de
enzimas EC 2/3 aproveitáveis.

## 1. Estado do trabalho

**Executado no PC:** preparação de 500 candidatos, sendo 428 de treino e 72 de
validação, em 489 grupos globais. Nenhum candidato pertence ao teste.
Os nove testes da preparação passaram. Os arquivos anexados foram conferidos:
o SHA-256 do CSV corresponde ao relatório e os IDs de texto correspondem ao CSV.

**Implementado neste pacote:** consulta ao UniProt, conferência exata da
sequência e separação dos candidatos com anotação revisada EC 2 ou EC 3.
Os testes usam dados sintéticos e respostas HTTP simuladas. A primeira consulta
real chegou à API e parou na conciliação dos IDs. A conclusão da consulta com
esta revisão e a cobertura EC obtida permanecem **[a confirmar]**.

**Planejado:** decidir se a cobertura permite um piloto com os embeddings
existentes; depois adaptar a entrada do classificador para os rótulos EC.
Este pacote não treina e não modifica o classificador da regra HILKMFTWV.

## 2. Instalação mínima

Extraia o ZIP fora de `C:\ai_tcc`. Copie seu conteúdo para `C:\ai_tcc`,
mesclando as pastas. O pacote contém somente três arquivos novos:

| Arquivo relativo a C:\ai_tcc | Finalidade |
| --- | --- |
| `etapas\consultar_sondagem_ec.py` | Cliente e conferência dos rótulos |
| `testes\test_consulta_ec.py` | Testes sem rede, modelos ou GPU |
| `docs\PILOTO_EC_CONSULTA.md` | Este guia |

Não há alteração de dependências. O script usa a biblioteca padrão do Python
e o ambiente virtual já existente. A consulta real requer internet com acesso
HTTPS a `rest.uniprot.org`; não requer chave de API ou conta Google.

## 3. Rodar os testes primeiro

No PowerShell:

```powershell
cd C:\ai_tcc
.\.venv\Scripts\python.exe -B -m unittest discover -s .\testes -p "test_consulta_ec.py" -v
```

O resultado esperado é **32 testes, OK**. A consulta real só é iniciada pelo
comando da próxima seção. Os testes não medem cobertura de EC.

## 4. Consultar os 500 IDs já preparados

```powershell
cd C:\ai_tcc
.\.venv\Scripts\python.exe -B .\etapas\consultar_sondagem_ec.py --sondagem ".\dados\piloto_ec2_ec3\sondagem_ids_20261014T005033529787Z_d557ab" --timeout 30 --espera-maxima 600
```

`--timeout` controla cada requisição HTTP. `--espera-maxima` controla a espera
do processamento de cada job no serviço; requisições e suas novas tentativas
também consomem tempo. São usados até três acessos para um GET que falhe por
conexão, timeout ou HTTP 429/500/502/503/504. Um POST de criação de job não é
reenviado automaticamente. Não há prazo de execução garantido.

O programa confere os três arquivos de preparação antes de consultar:
`candidatos.csv`, `ids_ncbi.txt` e `relatorio_preparacao.json`.
Modelo, revisão, hashes, IDs, partições e vínculos dos grupos precisam conferir.
Um candidato de teste, grupo compartilhado ou CSV adulterado bloqueia a execução.

## 5. Como o rótulo é aceito

1. Envia os IDs INSDC completos, preservando `.versão`, para o ID Mapping:
   `EMBL-GenBank-DDBJ_CDS → UniProtKB`. IDs RefSeq, quando presentes, usam
   `RefSeq_Protein`. O namespace INSDC foi conferido na configuração da API.
2. Aguarda o job e lê todas as páginas. Cada ID precisa ser explicado pela
   API em `results`, `failedIds` ou `suggestedIds`. As sugestões são pares
   `from`/`to` com destino UniParc `UPI...`, registrados separadamente.
   Duplicatas entre a resposta de status redirecionada e a página final são
   removidas por ID consultado e UPI. Respostas incompletas continuam bloqueadas.
3. Para IDs sem mapeamento, faz uma segunda consulta removendo somente o sufixo
   da versão. Registra ID original, ID enviado, ID retornado e modo de consulta.
   Essa tentativa não dispensa a conferência da sequência original.
4. Registra entradas revisadas e não revisadas separadamente. Apenas
   `UniProtKB reviewed (Swiss-Prot)` pode fornecer um rótulo aceito.
5. Exige comprimento e SHA-256 idênticos aos da sequência associada ao embedding.
   Não usa alinhamento, identidade aproximada, truncamento ou rótulo de um vizinho.
   Diferenças por isoforma, processamento da proteína ou versão podem reduzir a cobertura.
6. Lê EC explícito em `proteinDescription` ou `CATALYTIC ACTIVITY` e preserva
   as evidências retornadas pelo UniProt. Descrições como “transferase” não são rótulos.
7. Aceita uma única classe de primeiro nível: **EC 2 = Transferase** ou
   **EC 3 = Hidrolase**. Múltiplos ECs da mesma classe são permitidos.
   EC parcial com classe conhecida, como `2.7.1.-`, é permitido e sinalizado.
8. Exclui candidatos com classes conflitantes/múltiplas, inclusive EC 2 + EC 3
   ou EC 2 + outra classe. Sem anotação, EC fora do alvo e entradas não revisadas
   ficam fora do futuro treino. Não são uma terceira classe.

Uma sugestão UniParc não fornece, por si só, um rótulo EC revisado. O cliente
registra `sugestao_uniparc_sem_rotulo` quando só há esse tipo de retorno.
Não faz uma segunda cadeia UniParc → Swiss-Prot nesta etapa. A tentativa
com accession sem versão continua limitada aos IDs sem mapeamento UniProtKB;
ela preserva o ID original e exige o mesmo hash para aceitar qualquer rótulo.

Quando houver vários mapeamentos, os ECs das entradas revisadas de sequência
exata são considerados em conjunto. Uma proteína recebe no máximo um rótulo.
O rótulo não é propagado para os outros membros de seu grupo MMseqs2.

**Curadoria não é sinônimo de ensaio experimental:** o script guarda os códigos
de evidência, mas não exige que cada anotação tenha comprovação experimental.
O pacote não promete quantidade suficiente ou equilíbrio entre classes.

## 6. Arquivos produzidos

A saída fica em uma pasta nova dentro da sondagem:
`consulta_uniprot_DATA_HORA_IDENTIFICADOR`. Os três arquivos de entrada,
a base de um milhão, as partições e os modelos não são alterados.

| Saída | Conteúdo |
| --- | --- |
| `relatorio_consulta.json` | Cobertura, contagens, classes, partições, grupos, hashes e proveniência HTTP |
| `decisoes_candidatos.csv` | Uma linha por candidato, inclusive excluídos e sem anotação |
| `rotulos_ec_confirmados.csv` | Somente rótulos aceitos, com UID, índice original, grupo e partição preservados |
| `mapeamentos_uniprot.csv` | Mapeamentos, accessions, sequência exata/divergente, ECs e evidências |
| `sugestoes_uniparc.csv` | Pares sugeridos para UniParc, preservando IDs, modo, job e partição; sem atribuir EC |
| `respostas_api\` | Corpos JSON recebidos, headers relevantes, datas e parâmetros dos jobs |

“Confirmado” significa que o rótulo passou pelos critérios deste protocolo de
mapeamento; não representa validação biológica experimental feita pelo projeto.

A cobertura é contada por candidato, com denominador 500 nesta sondagem,
não por número de pares de mapeamento. O relatório separa mapeamento ao UniProt,
presença de entrada revisada, sequência revisada exata e rótulo EC aproveitável.
O release do UniProt é guardado quando enviado pelo servidor. Misturar releases
na mesma execução bloqueia a conclusão.

O campo `revisao_cliente` do relatório deve ser **2**. `resumos_jobs` detalha
IDs enviados, mapeados, em `failedIds` e com sugestão UniParc por job.
`tem_sugestao_uniparc` conta candidatos distintos, enquanto o CSV pode ter
mais de uma linha por candidato, por UPI ou por tentativa com/sem versão.
Um candidato pode ter uma entrada UniProtKB e uma sugestão UniParc;
essas contagens não devem ser somadas como categorias disjuntas.

## 7. Se falhar ou for interrompido

O relatório permanece `ok: false` e `resultados_ec2_ec3: null`.
Os arquivos já baixados são preservados. **Falha técnica não significa ausência
de anotação.** Ctrl+C marca a consulta como interrompida, sem iniciar treino.

Uma nova execução cria outra pasta e reenvia a sondagem; não retoma automaticamente
o job interrompido. Para apenas lentidão, pode repetir com `--timeout 60`.
Erros de certificado, resposta incompleta ou IDs inesperados precisam ser
diagnosticados pela mensagem; o script não ignora esses controles.

Para instalar esta correção, substitua somente os três arquivos de código,
teste e guia listados na seção 2. Preserve a consulta anterior com erro.
Depois dos testes, repita apenas a consulta aos 500 IDs da seção 4.
As etapas de geração do milhão de embeddings, MMseqs2 e treino não são repetidas.

## 8. O que conferir e enviar de volta

Depois de terminar com `ok: true`, envie:

- O resumo JSON do terminal ou `relatorio_consulta.json`;
- `rotulos_ec_confirmados.csv`;
- `decisoes_candidatos.csv`, se houver baixa cobertura ou muitas exclusões.

Vamos conferir quantas Transferases e Hidrolases existem por partição e por
grupo. A decisão seguinte será usar os vínculos existentes ou preparar um
piloto externo revisado do Swiss-Prot. Nenhum novo modelo foi avaliado no teste.

O número de enzimas EC 2/3 entre os descartes históricos acima de 512 resíduos
continua **[a confirmar]**, representado por `null`. Os 414.614 descartes históricos
acima desse limite são proteínas sem contagem EC estabelecida. Esta sondagem
parte de candidatos já filtrados e não pode recuperar essa informação.

## 9. Fontes técnicas primárias

- UniProt, configuração atual dos namespaces do ID Mapping:
  <https://rest.uniprot.org/configure/idmapping/fields>.
- UniProt, exemplo de acesso programático ao ID Mapping:
  <https://www.uniprot.org/help/id_mapping_prog>.
- UniProt, manual de anotação e referências cruzadas:
  <https://web.expasy.org/docs/userman.html>.
- UniProt, arquivo de sequências UniParc e identificadores UPI:
  <https://www.uniprot.org/help/uniparc>.
- UniProt API, artigo dos autores do serviço:
  <https://doi.org/10.1093/nar/gkaf394>.
- IUBMB, classes EC: <https://iubmb.qmul.ac.uk/enzyme/EC2/> e
  <https://iubmb.qmul.ac.uk/enzyme/EC3/>.

As fontes definem o serviço e a classificação EC. Elas não comprovam cobertura
dos 500 IDs; essa evidência será a saída da consulta real.
