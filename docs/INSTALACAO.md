# Guia de instalação — Sistema TCC

Versão 3.4 (novembro de 2026).

Para consultar proteínas, basta instalar o sistema: os três modelos do TCC vêm no Git. O MMseqs2 só é preciso para treinar o modelo EC 1 a EC 7, rodar fluxos novos ou agrupar arquivos do NCBI. O pacote de dados só é preciso para o mapa e as estatísticas da base de um milhão.

## O que você precisa

| Quero… | Instale | Tempo |
| --- | --- | --- |
| Usar o assistente guiado e consultar proteínas | Passo a passo básico | 10 a 20 min |
| Baixar arquivos .gz do NCBI pelo painel | Passo a passo básico | — |
| Treinar o EC 1 a EC 7, rodar um fluxo novo ou agrupar .gz | Básico + MMseqs2 (nativo **ou** WSL) | +2 min (nativo) ou +15 min e 1 reinício (WSL) |
| Ver o mapa e as estatísticas da base do milhão | Básico + pacote de dados (~1,7 GB) | depende do download |

## Requisitos

| Item | Detalhe |
| --- | --- |
| Windows | 10 (versão 2004 ou mais nova) ou 11 |
| Python | **não precisa instalar**: o `instalar.cmd` baixa um Python 3.13 próprio (via uv) para dentro do projeto |
| Git | [git-scm.com](https://git-scm.com/download/win). Sem Git, o `Instalar_TCC.cmd` oferece instalar pelo winget ou baixar o projeto em ZIP |
| Internet | para instalar as bibliotecas, baixar o ESM-2 (~30 MB, uma vez só) e coletar do NCBI e do UniProt |
| GPU NVIDIA | **opcional**; sem ela tudo roda no processador, com o mesmo resultado (consulta em cerca de 1 s). Placas AMD não são usadas |
| Administrador | **não é preciso**, exceto para o MMseqs2 no WSL |
| Espaço em disco | alguns GB para o ambiente Python (o PyTorch com GPU é o maior); +~10 GiB para fluxos novos (o sistema confere essa reserva) |
| Pasta | recomendado **C:\ai_tcc** (os relatórios da base do milhão registram esse caminho) |

## Passo a passo básico

Use uma janela **normal** (não "Executar como administrador").

1. **Rode `instalador\Instalar_TCC.cmd`.** Você pode baixar só esse arquivo do GitHub. Ele:
   - pergunta a pasta (Enter = `C:\ai_tcc`) e faz o `git clone`, ou `git pull` se o projeto já estiver lá;
   - roda o `instalar.cmd`, que baixa o uv, cria o `.venv` com Python 3.13 e instala as bibliotecas. Se já existir um `.venv` de outra versão, ele é guardado como `.venv_antigo_*`;
   - escolhe o PyTorch: CUDA 12.6 se houver placa NVIDIA, CPU nos demais casos;
   - baixa o ESM-2 e clona a coleta da segunda versão (repositório do Filipe) em `fase1_extrator\`;
   - pergunta **onde salvar os arquivos** (só neste PC ou uma pasta sincronizada do Google Drive, OneDrive ou Dropbox);
   - pergunta **como instalar o MMseqs2** (veja a seção abaixo);
   - oferece abrir o sistema.

   Leva de 5 a 15 minutos. Em redes lentas, ele tenta cada pacote até três vezes.
2. **Para abrir depois, dê dois cliques em `iniciar_sistema.cmd`.** Uma janela preta abre e o navegador mostra o **assistente guiado** em http://127.0.0.1:8765. O painel técnico fica em http://127.0.0.1:8765/avancado. Deixe a janela aberta e **não clique dentro dela** (se clicar, aperte Esc).
3. **Abra Configurações** (no painel avançado). Escolha o processamento (Automático, GPU ou CPU) e confira o diagnóstico (seção "Como conferir"). Mudou algo? Feche a janela preta com Ctrl+C **uma vez** e abra o `iniciar_sistema.cmd` de novo.
4. **Faça a primeira consulta** com a sequência de teste da seção "Como conferir".

Já tem o repositório clonado? Rode `instalar.cmd` na pasta do projeto e depois instale o MMseqs2 como abaixo.

## MMseqs2: nativo ou WSL

Só é preciso para treinar o EC 1 a EC 7, rodar um fluxo novo ou agrupar .gz. A consulta não precisa.

**Nativo do Windows (recomendado).** Não precisa de Linux nem de administrador, e foi validado em computador da faculdade. Escolha a opção 1 no `Instalar_TCC.cmd` ou rode `ferramentas\instalar_mmseqs_nativo.cmd`. O executável oficial `mmseqs-win64` é baixado para `ferramentas\mmseqs\`, e o modo **Automático** das Configurações passa a usá-lo.

**WSL + Ubuntu (alternativa).** É o mesmo ambiente da segunda versão.

1. Dê dois cliques em **`instalar_wsl_mmseqs.cmd`** (janela normal). Ele instala o Ubuntu no WSL, se faltar (pede permissão de administrador sozinho), instala o MMseqs2 dentro do Ubuntu e testa com `mmseqs version`.
2. Se ele acabou de instalar o Ubuntu: **reinicie o PC**, abra "Ubuntu" no menu Iniciar, crie um usuário e uma senha e **rode o `instalar_wsl_mmseqs.cmd` de novo**.
3. Se o seu Ubuntu tiver outro nome (por exemplo `Ubuntu-24.04`), escreva esse nome em **Configurações → Distribuição WSL**.

O modo pode ser fixado em **Configurações → MMseqs2** (Automático, WSL ou Nativo).

O TCC usou o MMseqs2 **18-8cc5c**. Outra versão funciona, mas o agrupamento de um fluxo novo pode sair um pouco diferente; a consulta e os modelos não mudam. O agrupamento do nativo ainda não foi comparado ao do WSL sobre o mesmo arquivo.

## Pacote de dados do milhão (opcional)

Sem o pacote, o sistema funciona: a consulta usa os modelos do repositório (aparece "Modelo do repositório") e a Visão geral mostra os números do TCC. O pacote (~1,7 GB) só libera o mapa e as estatísticas da base do milhão em Explorar e analisar.

1. Baixe o `pacote_dados_tcc.zip` e o `.sha256.txt` da pasta do grupo no Drive.
2. Confira o arquivo (o valor tem de ser igual ao do `.sha256.txt`):
   ```powershell
   Get-FileHash "$env:USERPROFILE\Downloads\pacote_dados_tcc.zip" -Algorithm SHA256
   ```
3. Extraia **dentro de C:\ai_tcc**, mantendo as pastas:
   ```powershell
   tar -xf "$env:USERPROFILE\Downloads\pacote_dados_tcc.zip" -C C:\ai_tcc
   ```
4. Reinicie o sistema. No diagnóstico, "Base do milhão" passa para OK.

Para gerar o pacote: `powershell -ExecutionPolicy Bypass -File ferramentas\empacotar_dados.ps1`. O arquivo sai em `C:\ai_tcc\saida\`.

## Como conferir que deu certo

**1. Diagnóstico (Configurações → Diagnóstico do ambiente).**

| Linha | Esperado | Se não estiver |
| --- | --- | --- |
| Python, PyTorch, Transformers | OK | rode `instalar.cmd` de novo |
| Processamento | OK | escolha Automático ou CPU e reinicie |
| Modelo ESM-2 em cache | OK | rode `instalar.cmd` de novo (precisa de internet) |
| Modelo da regra (prova de conceito), Modelo EC 2 × EC 3 | OK ("hash confere") | `git pull`; os modelos vêm no repositório |
| Modelo EC (7 classes) | OK | `git pull` |
| Fase 1 (Filipe) | OK | rode `instalar.cmd` de novo (ele clona o repositório) |
| Base do milhão | Opcional | só com o pacote de dados |
| WSL + MMseqs2 | OK no modo WSL | rode `instalar_wsl_mmseqs.cmd`. **Com o MMseqs2 nativo, esta linha pode ficar pendente**: ela testa apenas o WSL |

**2. Consulta de teste.** No assistente guiado (Consultar) ou no painel avançado (Consultar proteína), cole esta hidrolase do Swiss-Prot (A1KKY1):

```
MPKSRRAVSLSVLIGAVIAALAGALIAVTVPARPNRPEADREALWKIVHDRCEFGYRRTGAYAPCTFVDEQSGTALYKADFDPYQFLLIPLARITGIEDPALRESAGRNYLYDAWAARFLVTARLNNSLPESDVVLTINPKNARTQDQLHIHISCSSPTTSAALRNVDTSEYVGWKQLPIDLGGRRFQGLAVDTKAFESRNLFRDIYLKVTADGKKMENASIAVANVAQDQFLLLLAEGTEDQPVAAETLQDHDCSITKS
```

O esperado é **Hidrolase (EC 3)** no modelo principal (EC 1 a EC 7). O modelo EC 2 × EC 3 e a regra dos nove aminoácidos aparecem em "Ver outros modelos". O resultado é igual na GPU e na CPU, até a sexta casa decimal do escore.

**3. Testes automáticos (opcional).** Com o sistema fechado:

```powershell
cd C:\ai_tcc
.venv\Scripts\python.exe -m unittest discover -s testes
```

Termina com `OK`. Se um teste de tempo falhar com o PC ocupado, rode de novo.

## Problemas comuns

| Sintoma | Solução |
| --- | --- |
| `instalar.cmd` falha ao baixar o uv ou o Python | Verifique internet, antivírus e proxy (precisa de acesso ao github.com) e rode de novo |
| SmartScreen avisa ao abrir o `.exe` do instalador | Normal: o executável gerado pelo IExpress não tem assinatura digital. Clique em "Mais informações" → "Executar assim mesmo" |
| Painel mostra "Sistema desconectado" | Confira se a janela preta está aberta e fora do modo "Selecionar" (Esc). Espere 1 minuto e aperte F5 |
| Consulta bloqueada com "Modelo indisponível" | `git pull` na pasta do projeto e veja o diagnóstico |
| "GPU (CUDA) escolhida… indisponível" | Em Configurações, escolha Automático ou CPU e reinicie o sistema |
| Explorar diz "A base do milhão não está neste PC" | Normal sem o pacote: escolha uma execução nova no seletor do topo ou instale o pacote de dados |
| Etapa do MMseqs2 falha por tempo (WSL) | O WSL demorou a acordar: rode `wsl -d Ubuntu --exec mmseqs version` e tente de novo, ou use o MMseqs2 nativo |
| `Failed to start the systemd user session` | `wsl -d Ubuntu -u root --exec sed -i 's/systemd=true/systemd=false/' /etc/wsl.conf`, depois `wsl --shutdown` |
| Download do NCBI falha | O sistema tenta FTP e depois HTTPS sozinho; se os dois falharem, a rede bloqueia o NCBI |
| Coleta do UniProt para com erro HTTP 500 | O serviço do UniProt falhou; os arquivos parciais ficam preservados. Use "continuar" mais tarde |
| Fila parada depois de fechar o sistema | No painel avançado, em Pipeline automático, clique em "Retomar fila". Para fechar o sistema, aperte Ctrl+C só uma vez |

## Atualizar depois

Rode o `Instalar_TCC.cmd` de novo (ele faz `git pull`) ou, com o sistema fechado:

```powershell
cd C:\ai_tcc
git pull
```

Só rode o `instalar.cmd` outra vez se o `requirements.txt` tiver mudado.

**O que vem no Git:** o código, o assistente e o painel, os testes, a documentação e os três modelos em `dados\modelos\`.

**O que fica só no seu PC:** o `.venv`, o cache do ESM-2, a base do milhão, as execuções novas, os `.gz` baixados, `fase1_extrator\`, `ferramentas\mmseqs\` e o `config_local.json` com as suas configurações.

## Salvar na nuvem (opcional)

Na pergunta do instalador ou em **Configurações → Pasta na nuvem**, aponte uma pasta já sincronizada neste PC (ex.: `G:\Meu Drive\TCC`). Você escolhe o que vai para lá:

- os `.gz` e CSVs do NCBI (o sistema também os lê dessa pasta);
- cópias das execuções e dos treinos do EC 1 a EC 7 ao terminarem.

A fila (`controle.sqlite3`), os logs, o cache e os modelos ficam sempre no PC, porque um banco SQLite em pasta sincronizada pode ser corrompido. Reinicie o sistema depois de mudar essa opção.
