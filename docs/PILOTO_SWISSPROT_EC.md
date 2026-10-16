# Piloto Swiss-Prot — coleta de Transferases e Hidrolases

Projeto: Inteligência Artificial Aplicada à Genética e Bioinformática  
Protocolo definido em 13/10/2026, America/Sao_Paulo — revisão 1

## 1. Por que esta etapa existe

A sondagem dos 500 IDs do recorte NCBI foi concluída no PC, com a revisão 2 do
cliente UniProt e os 32 testes aprovados. Foram obtidos 176 candidatos com
mapeamento UniProtKB, 14 com entrada revisada e 6 com sequência revisada exata.
Os seis não tinham EC explícito; os outros oito revisados tinham sequência
divergente. Nenhum rótulo EC 2/EC 3 passou pelos critérios dessa sondagem.
O resultado se restringe aos 500 candidatos e ao protocolo adotado.

**Próxima decisão adotada:** preparar um piloto externo a partir de anotações
revisadas do Swiss-Prot. O alvo permanece **Transferases (EC 2) versus
Hidrolases (EC 3)**. O MLP da regra HILKMFTWV continua como experimento
preliminar já executado; sua acurácia não é resultado deste novo alvo.

**Implementado neste pacote:** download limitado, auditoria de rótulos,
filtros, deduplicação e seleção determinística. Os 25 testes locais usam
dados sintéticos e respostas HTTP simuladas. A coleta real e a quantidade
de exemplos aproveitáveis permanecem **[a confirmar]**.

**Planejado para depois:** agrupamento deste piloto, partições por grupo,
embeddings com o mesmo ESM-2, adaptação do classificador e avaliação EC.
O relatório desta coleta mantém `treinamento_liberado: false`.

## 2. Arquivos e ambiente

Copie os três arquivos novos do ZIP para `C:\ai_tcc`, mesclando as pastas:

| Arquivo relativo ao projeto | Finalidade |
| --- | --- |
| `etapas\baixar_piloto_swissprot_ec.py` | Coleta e auditoria |
| `testes\test_coleta_swissprot_ec.py` | Testes sem rede ou GPU |
| `docs\PILOTO_SWISSPROT_EC.md` | Este guia |

O coletor reutiliza `etapas\consultar_sondagem_ec.py`, revisão 2, que já foi
validado no PC. Mantenha esse arquivo na mesma pasta. A biblioteca padrão do
Python e a `.venv` existente bastam. A coleta usa HTTPS em `rest.uniprot.org`.

O milhão de vetores, grupos e partições existentes permanece preservado.
Nenhum modelo é carregado nesta etapa. Os dados novos ficam em outra pasta.

## 3. Testes primeiro

```powershell
cd C:\ai_tcc
.\.venv\Scripts\python.exe -B -m unittest discover -s .\testes -p "test_coleta_swissprot_ec.py" -v
```

Resultado esperado: **25 testes, OK**. Eles verificam rótulos explícitos,
revisão, limite de comprimento, conflitos de classe, sequências duplicadas,
paginação, proveniência, preservação dos dados históricos e falhas técnicas.

## 4. Executar a coleta

Depois de os testes passarem:

```powershell
cd C:\ai_tcc
.\.venv\Scripts\python.exe -B .\etapas\baixar_piloto_swissprot_ec.py --por-classe 500 --candidatos-por-classe 2000 --semente 42 --timeout 30
```

O comando busca até 2.000 candidatos de cada consulta, totalizando no máximo
4.000 registros retornados para auditoria. Accessions que apareçam nas duas
consultas são unificadas na auditoria. A meta é selecionar até **500 sequências
únicas por classe**, após os filtros. A quantidade efetiva será medida.

O contador durante o download se refere aos candidatos; o resumo final se
refere às sequências selecionadas. Não há promessa de prazo de download.
O timeout é de cada requisição HTTP; falhas transitórias em GET têm novas
tentativas limitadas pelo cliente já instalado.

## 5. Protocolo de seleção, fixado antes do treino

As consultas são:

- EC 2: `(reviewed:true) AND (ec:2.-.-.-)`;
- EC 3: `(reviewed:true) AND (ec:3.-.-.-)`.

Cada consulta é ordenada por `accession asc` e limitada aos primeiros
candidatos do protocolo. O download não aplica filtro de comprimento: isso
permite contar as exclusões acima de 512 resíduos entre os candidatos obtidos.

A auditoria aplica os seguintes critérios:

1. Entrada revisada do Swiss-Prot com sequência e comprimento coerentes.
2. EC explícito em `proteinDescription` ou `CATALYTIC ACTIVITY`, preservando
   os códigos de evidência recebidos. Nome da proteína não define rótulo.
3. Uma única classe EC de primeiro nível, 2 ou 3. Múltiplos ECs da mesma classe
   são aceitos; EC parcial com classe conhecida é sinalizado e permitido.
4. Comprimento de **1 a 512 resíduos**, sem truncamento, e alfabeto compatível
   com o pipeline anterior: `ACDEFGHIKLMNPQRSTVWYBXZUO`.
5. Sequências idênticas são agrupadas por SHA-256. Anotações revisadas de
   classes conflitantes para a mesma sequência excluem essa sequência.
   Duplicatas com a mesma classe mantêm uma representante com rastreabilidade.
6. Entre as representantes elegíveis, os menores valores de
   `SHA256(semente:SHA256_da_sequencia)` são selecionados por classe.
   Os UIDs `ec000000000`, etc., não codificam a classe do exemplo.

Sem EC, fora do alvo, multiclasse e não revisado são motivos de exclusão;
não viram uma terceira classe. A quantidade de sequências menores que 30
resíduos é registrada por classe, mantendo o limite inferior do protocolo
anterior. Os motivos de exclusão podem se sobrepor.

**Limitação da amostragem:** a seleção por hash ocorre dentro do conjunto
limitado por accession. Ela não transforma esse recorte em amostra aleatória
de todo o Swiss-Prot. A meta equilibrada por classe também não representa
a frequência dessas classes na natureza ou no NCBI.

**Limitação dos rótulos:** revisão no Swiss-Prot não significa que cada
anotação tenha comprovação experimental direta. As evidências são guardadas
para inspeção; o projeto não realiza validação biológica experimental.

## 6. Saídas e conferência

Uma pasta nova é criada em:

`C:\ai_tcc\dados\piloto_ec2_ec3\swissprot_DATA_HORA_IDENTIFICADOR\`

| Arquivo | Conteúdo |
| --- | --- |
| `relatorio_coleta.json` | Quantidades reais, filtros, comprimentos por classe, fonte, release e hashes |
| `candidatos_auditados.csv` | Candidatos únicos, anotações, evidências, exclusões e situação na seleção |
| `piloto_rotulado.csv` | Sequências selecionadas, rótulo, UID, índice e SHA-256 |
| `sequencias.fasta` | Mesmas sequências e ordem do CSV; cabeçalhos contêm somente o UID |
| `respostas_api\` | Corpos JSON e metadados das respostas para auditoria |

Conferir no JSON final:

- `ok: true`: coleta e auditoria concluídas;
- `amostra_completa`: se a meta foi atingida;
- `rotulos_selecionados`: quantidades de Transferases e Hidrolases;
- `exclusoes_comprimento`: exclusões acima de 512 no conjunto auditado;
- `comprimentos_por_classe`: mínimo, mediana, máximo e quantidade abaixo de 30;
- `agrupamento_global` e `particoes_por_grupos`: ainda pendentes.

As contagens de comprimento se restringem a esta coleta. O número de enzimas
EC 2/EC 3 nos descartes históricos do milhão continua desconhecido (`null`).
Entradas maiores que 512 podem aparecer no CSV de auditoria para comprovar
a exclusão; não aparecem no FASTA selecionado.

Em falha técnica, `ok` fica falso, as contagens finais permanecem `null` e
as respostas obtidas são preservadas. Uma execução posterior cria outra pasta.
Não é retomada automática. O relatório só permite tratar a coleta como
concluída quando `ok: true`. Amostra menor que a meta é declarada explicitamente.

## 7. O que enviar e o que vem depois

Cole o resumo JSON do terminal. Para conferir a composição, também podem ser
enviados `relatorio_coleta.json` e `piloto_rotulado.csv`.

Depois de conferir o conjunto, a próxima etapa será preparar o piloto para
IA: agrupar globalmente suas sequências, separar os grupos e gerar embeddings
com `facebook/esm2_t6_8M_UR50D`, revisão
`c731040fcd8d73dceaa04b0a8e6329b345b0f5df`.

Os grupos e índices antigos pertencem ao recorte do milhão e não são atribuídos
automaticamente a sequências externas. O mesmo modelo, os parâmetros de
agrupamento e o código podem ser reaproveitados com os vínculos novos.
Reutilizar um embedding histórico exige sequência idêntica e configuração
compatível; esta coleta não procura nem carrega esses vetores.

O futuro teste EC será reservado até o protocolo de treino estar fechado.
Nesta etapa não há treino, escolha de hiperparâmetros ou avaliação de teste.

## 8. Fontes técnicas primárias

- UniProt, busca por entradas revisadas com EC 2:
  <https://www.uniprot.org/uniprotkb?query=(ec%3A2.-.-.-)%20AND%20(reviewed%3Atrue)>.
- UniProt, campos de consulta: <https://www.uniprot.org/help/query-fields>.
- UniProt, acesso programático: <https://www.uniprot.org/help/api_queries>.
- UniProt API, artigo dos autores: <https://doi.org/10.1093/nar/gkaf394>.
- Manual de anotação: <https://web.expasy.org/docs/userman.html>.
- Classes EC: <https://iubmb.qmul.ac.uk/enzyme/EC2/> e
  <https://iubmb.qmul.ac.uk/enzyme/EC3/>.

Essas fontes fundamentam a consulta e a classificação. A quantidade realmente
obtida e as exclusões do piloto serão comprovadas pela execução no PC.
