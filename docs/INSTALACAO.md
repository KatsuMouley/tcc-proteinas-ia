# Guia de instalação — Sistema TCC

25/10/2026 · cópia do guia publicado para o grupo (link na pasta do grupo)

Para consultar proteínas no painel basta clonar o repositório e rodar dois arquivos: os três modelos do TCC vêm no git. WSL, MMseqs2 e o pacote de dados só entram se você for rodar fluxos novos ou ver o mapa do milhão.

## O que você precisa

| Quero… | Instale | Tempo |
| --- | --- | --- |
| Abrir o painel e consultar proteínas (regra, EC 2 × EC 3 e EC 7 classes) | Passo a passo básico | 10 a 20 min |
| Baixar arquivos .gz do NCBI pelo painel | Passo a passo básico | — |
| Agrupar .gz (Fase 1), rodar um fluxo novo ou o experimento EC7 | Básico + Opcional A (WSL + MMseqs2) | +15 min e 1 reinício |
| Ver o mapa e as estatísticas da base do milhão | Básico + Opcional B (pacote de dados, ~1,7 GB) | depende do download |

## Requisitos

| Item | Detalhe |
| --- | --- |
| Windows | 10 (versão 2004 ou mais nova) ou 11 |
| Python | **3.13** ([python.org](https://www.python.org/downloads/)); na instalação, marque "Add python.exe to PATH" |
| Git | [git-scm.com](https://git-scm.com/download/win) |
| Internet | para instalar as bibliotecas e baixar o ESM-2 (~30 MB, uma vez só) |
| GPU NVIDIA | **opcional**; sem ela tudo roda no processador (consulta em cerca de 1 s) |
| Espaço em disco | reserve alguns GB para o ambiente Python (o PyTorch com GPU é o maior); +~10 GB se for rodar fluxos novos |
| Pasta | o projeto precisa ficar em **C:\ai_tcc** |

## Passo a passo básico

Use um PowerShell **normal** (não "Executar como administrador").

1. **Clone o repositório em C:\ai_tcc.** Os relatórios do TCC registram esse caminho.
   ```powershell
   git clone https://github.com/KatsuMouley/tcc-proteinas-ia.git C:\ai_tcc
   ```
2. **Dê dois cliques em `instalar.cmd`.** Ele cria o ambiente `.venv`, instala as bibliotecas, escolhe o PyTorch certo (GPU NVIDIA se houver, senão CPU), baixa o ESM-2 e clona a Fase 1 do Filipe em `fase1_extrator\`. Leva de 5 a 15 minutos. Se ele avisar que a pasta não é C:\ai_tcc, cancele e clone no lugar certo.
3. **Dê dois cliques em `iniciar_sistema.cmd`.** Uma janela preta abre e o painel aparece em http://127.0.0.1:8765. Deixe a janela aberta e **não clique dentro dela** (se clicar, aperte Esc).
4. **Abra Configurações no painel.** Escolha o processamento (Automático, GPU ou CPU) e confira o Diagnóstico (seção "Como conferir"). Mudou algo? Feche a janela preta com Ctrl+C **uma vez** e abra o `iniciar_sistema.cmd` de novo.
5. **Faça a primeira consulta** em Consultar proteína, com a sequência de teste da seção "Como conferir".

## Opcional A: WSL + Ubuntu + MMseqs2

Só é preciso para agrupar (Fase 1), rodar um fluxo novo ou o experimento EC7. A consulta não precisa.

1. Dê dois cliques em **`instalar_wsl_mmseqs.cmd`**, na pasta do projeto (janela normal). Ele:
   - instala o Ubuntu no WSL, se faltar (pede permissão de administrador sozinho);
   - instala o MMseqs2 dentro do Ubuntu, sem pedir senha;
   - testa com `mmseqs version`.
2. Se ele acabou de instalar o Ubuntu: **reinicie o PC**, abra "Ubuntu" no menu Iniciar, crie um usuário e uma senha, feche e **rode o `instalar_wsl_mmseqs.cmd` de novo**.
3. Ele termina com `OK: Ubuntu com MMseqs2 …`. Se o seu Ubuntu tiver outro nome (por exemplo `Ubuntu-24.04`), escreva esse nome em **Configurações → Distribuição WSL**.

O TCC usou o MMseqs2 **18-8cc5c**. Outra versão funciona, mas o agrupamento de um fluxo novo pode sair um pouco diferente; a consulta e os modelos não mudam. O instalador avisa quando a versão não é a 18.

## Opcional B: pacote de dados do milhão

Sem o pacote, o painel funciona: a consulta usa os modelos do repositório (aparece "Modelo do repositório") e a Visão geral mostra os números do TCC. O pacote (~1,7 GB) só libera o mapa e as estatísticas da base do milhão em Explorar e analisar.

1. Peça ao Katsu o `pacote_dados_tcc.zip` e o arquivo `.sha256.txt` (pasta do grupo no Drive).
2. Confira o arquivo (o valor tem de ser igual ao do `.sha256.txt`):
   ```powershell
   Get-FileHash "$env:USERPROFILE\Downloads\pacote_dados_tcc.zip" -Algorithm SHA256
   ```
3. Extraia **dentro de C:\ai_tcc**, mantendo as pastas:
   ```powershell
   tar -xf "$env:USERPROFILE\Downloads\pacote_dados_tcc.zip" -C C:\ai_tcc
   ```
4. Reinicie o sistema. No Diagnóstico, "Base do milhão" passa para OK.

Quem gera o pacote (só o Katsu): `powershell -ExecutionPolicy Bypass -File ferramentas\empacotar_dados.ps1`. O arquivo sai em `C:\ai_tcc\saida\`.

## Como conferir que deu certo

**1. Diagnóstico (Configurações → Diagnóstico do ambiente).** Para consultar, as linhas abaixo têm de estar OK; as marcadas "Opcional" podem ficar pendentes.

| Linha | Esperado | Se não estiver |
| --- | --- | --- |
| Python, PyTorch, Transformers | OK | rode `instalar.cmd` de novo |
| Processamento | OK | escolha Automático ou CPU e reinicie |
| Modelo ESM-2 em cache | OK | rode `instalar.cmd` de novo (precisa de internet) |
| Modelo da regra, Modelo EC 2 × EC 3 | OK ("hash confere") | `git pull`; os modelos vêm no repositório |
| Modelo EC (7 classes) | OK | `git pull` |
| Base do milhão | Opcional | só com o pacote de dados (Opcional B) |
| WSL + MMseqs2 | Pendente sem o Opcional A | `instalar_wsl_mmseqs.cmd` |

**2. Consulta de teste.** Em Consultar proteína, cole esta hidrolase do Swiss-Prot (A1KKY1) e clique em consultar:

```
MPKSRRAVSLSVLIGAVIAALAGALIAVTVPARPNRPEADREALWKIVHDRCEFGYRRTGAYAPCTFVDEQSGTALYKADFDPYQFLLIPLARITGIEDPALRESAGRNYLYDAWAARFLVTARLNNSLPESDVVLTINPKNARTQDQLHIHISCSSPTTSAALRNVDTSEYVGWKQLPIDLGGRRFQGLAVDTKAFESRNLFRDIYLKVTADGKKMENASIAVANVAQDQFLLLLAEGTEDQPVAAETLQDHDCSITKS
```

No PC do Katsu o resultado foi **Hidrolase (EC 3)** nos dois modelos: 77,6% no EC 2 × EC 3 e 70,7% no de 7 classes, com regra "Completa". Em CPU os números podem variar na última casa.

**3. Testes automáticos (opcional).** Com o painel fechado:

```powershell
cd C:\ai_tcc
.venv\Scripts\python.exe -m unittest discover -s testes
```

Termina com `OK` (114 testes). Se um teste de tempo falhar com o PC ocupado, rode de novo.

## Problemas comuns

| Sintoma | Solução |
| --- | --- |
| `instalar.cmd` não acha o Python | Instale o Python 3.13 marcando "Add python.exe to PATH" e rode de novo |
| Painel mostra "Sistema desconectado" | Confira se a janela preta está aberta e fora do modo "Selecionar" (Esc). Espere 1 minuto e aperte F5 |
| Consulta bloqueada com "Modelo indisponível" | `git pull` na pasta C:\ai_tcc e veja o Diagnóstico |
| "GPU (CUDA) escolhida… indisponível" | Em Configurações, escolha Automático ou CPU e reinicie o sistema |
| Explorar diz "A base do milhão não está neste PC" | Normal sem o pacote: escolha uma execução nova no seletor do topo ou faça o Opcional B |
| WSL não responde / some o Ubuntu | Use um PowerShell **normal**, não de administrador. Rode `wsl -l -v` para ver o nome do Ubuntu |
| `Failed to start the systemd user session` | `wsl -d Ubuntu -u root --exec sed -i 's/systemd=true/systemd=false/' /etc/wsl.conf`, depois `wsl --shutdown` |
| Etapa do MMseqs2 falha por tempo | O WSL demorou a acordar: rode `wsl -d Ubuntu --exec mmseqs version` e tente de novo |
| Download do NCBI falha | O sistema tenta FTP e depois HTTPS sozinho; se os dois falharem, a rede bloqueia o NCBI |
| Fila do painel parada depois de fechar | Na página Pipeline, clique em "Retomar fila". Para fechar o sistema, aperte Ctrl+C só uma vez |

## Atualizar depois

Com o sistema fechado:

```powershell
cd C:\ai_tcc
git pull
```

Depois abra o `iniciar_sistema.cmd` de novo. Só rode o `instalar.cmd` outra vez se o `requirements.txt` tiver mudado.

**O que vem no git:** o código, o painel, os testes, a documentação e os três modelos em `dados\modelos\`.

**O que fica só no seu PC:** o `.venv`, o cache do ESM-2, a base do milhão, as execuções novas, os `.gz` baixados, a Fase 1 do Filipe (o instalador clona) e o `config_local.json` com as suas Configurações.
