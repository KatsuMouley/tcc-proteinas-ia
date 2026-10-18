import os
import gzip
import shutil
import subprocess
import csv
import logging
import zlib
from datetime import datetime, timedelta

# ==========================================
# 1. VARIÁVEIS DE CAMINHOS
# ==========================================

download_path = "C:/Users/filip/Downloads/codigos_gerar_genes"
# Arquivo que apenas anota quem já foi feito (para o script pular)
ARQUIVO_LOG = os.path.join(download_path, "historico_arquivos_processados.txt")
# Novo arquivo de log geral do sistema (onde tudo fica registrado)
ARQUIVO_LOG_SISTEMA = os.path.join(download_path, "log.txt")

NOME_AUTOMACAO = "Agrupamento MMseqs2"

# Chamamos o motor do Linux
EXECUTAVEL_LINUX = "wsl"

g_drive = "G:/Meu Drive/TCC/base_genes_tcc"
DIR_GZ = os.path.join(g_drive, "arquivos_gz")

# Nova pasta no Google Drive para salvar os CSVs individuais
DIR_CSV_DRIVE = os.path.join(g_drive, "csv_resultados")
os.makedirs(DIR_CSV_DRIVE, exist_ok=True)

# Pasta local temporária para não pesar o Drive
DIR_TEMP_LOCAL = "C:/temp_base_genes"

os.makedirs(DIR_TEMP_LOCAL, exist_ok=True)

# Lista dos 9 aminoácidos essenciais (código de 1 letra)
AMINOACIDOS_ESSENCIAIS = {'H', 'I', 'L', 'K', 'M', 'F', 'T', 'W', 'V'}

# ==========================================
# 2. SISTEMA DE LOGS E CONTROLE
# ==========================================
def setup_logging(log_path, dias_manter=5):
    if os.path.exists(log_path):
        try:
            mod_time = os.path.getmtime(log_path)
            agora = datetime.now()
            idade = agora - datetime.fromtimestamp(mod_time)
            
            if idade > timedelta(days=dias_manter):
                os.remove(log_path)
                print(f"[SISTEMA] Log antigo de {idade.days} dias removido com sucesso.")
        except Exception as e:
            print(f"[AVISO] Não foi possível remover log antigo: {e}")

    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_path, encoding='utf-8', mode='a'),
            logging.StreamHandler()
        ]
    )
    logging.info(f"--- INICIANDO {NOME_AUTOMACAO} ---")

def carregar_arquivos_ja_processados():
    if not os.path.exists(ARQUIVO_LOG):
        return set()
    with open(ARQUIVO_LOG, 'r', encoding='utf-8') as log:
        return set(linha.strip() for linha in log)

def registrar_sucesso(nome_arquivo):
    with open(ARQUIVO_LOG, 'a', encoding='utf-8') as log:
        log.write(nome_arquivo + '\n')

def descompactar_gz(caminho_gz, caminho_fasta):
    nome_arquivo = os.path.basename(caminho_gz)
    logging.info(f"Extraindo: {nome_arquivo}")
    try:
        with gzip.open(caminho_gz, 'rb') as f_in:
            with open(caminho_fasta, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        return True
    except (gzip.BadGzipFile, EOFError, zlib.error) as e:
        logging.error(f"ERRO CRITICO: O arquivo {nome_arquivo} esta corrompido ou incompleto. Pulando...")
        if os.path.exists(caminho_fasta):
            os.remove(caminho_fasta)
        return False

def rodar_mmseqs(caminho_fasta, pasta_saida):
    nome_arquivo_apenas = os.path.basename(caminho_fasta)
    logging.info(f"Agrupando proteinas de: {nome_arquivo_apenas} com MMseqs2...")
    
    # O MMseqs2 processando arquivos do Windows (/mnt/c) gera um gargalo enorme de memória e I/O (sistema 9P do WSL).
    # Para resolver o "travamento" e consumo excessivo de memória, fazemos o processamento todo dentro do Linux (/tmp)
    pasta_db_tmp_wsl = f"/tmp/mmseqs_{nome_arquivo_apenas}"
    subprocess.run([EXECUTAVEL_LINUX, "mkdir", "-p", pasta_db_tmp_wsl])
    
    nome_db = f"{pasta_db_tmp_wsl}/db"
    nome_db_clu = f"{pasta_db_tmp_wsl}/clu"
    nome_saida_tsv = f"{pasta_db_tmp_wsl}/{nome_arquivo_apenas}_mmseqs_out.tsv"
    
    # Converte o caminho do Windows (C:/temp_base_genes/...) para o padrão do WSL (/mnt/c/temp_base_genes/...)
    caminho_fasta_wsl = caminho_fasta.replace("\\", "/").replace("C:", "/mnt/c").replace("c:", "/mnt/c")
    
    # 1. Converte o FASTA em banco de dados interno do MMseqs2 (direto no Linux)
    cmd_createdb = [EXECUTAVEL_LINUX, "mmseqs", "createdb", caminho_fasta_wsl, nome_db]
    
    # 2. Faz o clustering (escrevendo temporários no Linux, muito mais rápido)
    cmd_cluster = [EXECUTAVEL_LINUX, "mmseqs", "cluster", nome_db, nome_db_clu, pasta_db_tmp_wsl, "--min-seq-id", "0.5", "-c", "0.8"]
    
    # 3. Transforma o resultado num arquivo TSV legível
    cmd_createtsv = [EXECUTAVEL_LINUX, "mmseqs", "createtsv", nome_db, nome_db, nome_db_clu, nome_saida_tsv]
    
    # 4. Copia apenas o TSV final pronto para a pasta do Windows
    caminho_tsv_win_wsl = os.path.join(pasta_saida, f"{nome_arquivo_apenas}_mmseqs_out.tsv").replace("\\", "/").replace("C:", "/mnt/c").replace("c:", "/mnt/c")
    cmd_copy = [EXECUTAVEL_LINUX, "cp", nome_saida_tsv, caminho_tsv_win_wsl]
    
    # 5. Apaga a pasta temporária do Linux para liberar espaço
    cmd_cleanup = [EXECUTAVEL_LINUX, "rm", "-rf", pasta_db_tmp_wsl]

    try:
        subprocess.run(cmd_createdb, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(cmd_cluster, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(cmd_createtsv, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(cmd_copy, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(cmd_cleanup, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        logging.error(f"Erro ao agrupar o arquivo {nome_arquivo_apenas} no MMseqs2.")
        return False

def extrair_dicionario_fasta(caminho_fasta):
    seqs = {}
    with open(caminho_fasta, 'r', encoding='utf-8') as f:
        header = ''
        seq = []
        for line in f:
            linha = line.strip()
            if linha.startswith('>'):
                if header:
                    seqs[header] = "".join(seq)
                header = linha.split()[0].replace('>', '') 
                seq = []
            else:
                seq.append(linha)
        if header:
            seqs[header] = "".join(seq)
    return seqs

def verificar_tipo_nutricional(sequencia):
    if not sequencia or sequencia == "Sequência não encontrada":
        return "N/A"
    
    letras_presentes = set(sequencia.upper())
    if AMINOACIDOS_ESSENCIAIS.issubset(letras_presentes):
        return "Completa"
    else:
        return "Incompleta"

def salvar_resultados_no_csv(pasta_temp, arquivo_origem, caminho_fasta_original):
    import gc
    dicionario_sequencias = extrair_dicionario_fasta(caminho_fasta_original)
    
    # Cria um CSV exclusivo para este arquivo .gz diretamente no Google Drive
    nome_base = arquivo_origem.replace('.gz', '')
    arquivo_csv_individual = os.path.join(DIR_CSV_DRIVE, f"{nome_base}.csv")
    
    with open(arquivo_csv_individual, 'w', newline='', encoding='utf-8') as csv_out:
        escritor = csv.writer(csv_out, delimiter=';')
        # Escreve o cabeçalho no novo arquivo (SEM a sequência completa para não explodir o disco)
        escritor.writerow(['Arquivo_Origem', 'Grupo_Similaridade', 'ID_da_Proteina', 'Tipo_Nutricional'])
        
        for item in os.listdir(pasta_temp):
            # O MMseqs gera arquivos tabulares .tsv maravilhosos (sem sujeira e confusão como o clstr)
            if item.endswith('_mmseqs_out.tsv'):
                caminho_completo = os.path.join(pasta_temp, item)
                
                with open(caminho_completo, 'r', encoding='utf-8') as f_in:
                    for linha in f_in:
                        linha_limpa = linha.strip()
                        if not linha_limpa:
                            continue
                        
                        # O TSV vem como: Representante (Cluster) [tab] Proteína_Membro
                        partes = linha_limpa.split('\t')
                        if len(partes) >= 2:
                            representante = partes[0]
                            membro = partes[1]
                            
                            cluster_atual = f"Grupo_{representante}"
                            id_proteina = membro
                                
                            seq_completa = dicionario_sequencias.get(id_proteina, "Sequência não encontrada")
                            tipo_nutri = verificar_tipo_nutricional(seq_completa)
                            
                            escritor.writerow([arquivo_origem, cluster_atual, id_proteina, tipo_nutri])
                            
    # Limpa a memória para evitar acúmulo entre um arquivo e outro
    del dicionario_sequencias
    gc.collect()

# ==========================================
# 3. FLUXO PRINCIPAL DE EXECUÇÃO
# ==========================================
def iniciar_automacao():
    setup_logging(ARQUIVO_LOG_SISTEMA)
    
    processados = carregar_arquivos_ja_processados()
    arquivos_gz = [f for f in os.listdir(DIR_GZ) if f.endswith('.gz')]

    logging.info(f"Total de arquivos .gz encontrados: {len(arquivos_gz)}")
    logging.info(f"Arquivos já processados anteriormente: {len(processados)}")
    
    for arquivo in arquivos_gz:
        if arquivo in processados:
            logging.info(f"Pulando {arquivo} (Já processado).")
            continue
            
        caminho_gz = os.path.join(DIR_GZ, arquivo)
        
        nome_base = arquivo.replace('.gz', '')
        if '.' in nome_base:
            nome_fas = nome_base.split('.')[0] + ".fas"
        else:
            nome_fas = nome_base + ".fas"
            
        caminho_fasta_local = os.path.join(DIR_TEMP_LOCAL, nome_fas)
        
        descompactado_com_sucesso = descompactar_gz(caminho_gz, caminho_fasta_local)
        
        if not descompactado_com_sucesso:
            continue
        
        sucesso = rodar_mmseqs(caminho_fasta_local, DIR_TEMP_LOCAL)
        
        if sucesso:
            salvar_resultados_no_csv(DIR_TEMP_LOCAL, arquivo, caminho_fasta_local)
            registrar_sucesso(arquivo)
            logging.info(f"Sucesso! {arquivo} consolidado no seu respectivo CSV.")
            
        for item in os.listdir(DIR_TEMP_LOCAL):
            caminho_item = os.path.join(DIR_TEMP_LOCAL, item)
            try:
                if os.path.isdir(caminho_item):
                    shutil.rmtree(caminho_item)
                else:
                    os.remove(caminho_item)
            except Exception:
                pass

    logging.info("Mesclando todos os arquivos CSV em um único arquivo final...")
    ARQUIVO_FINAL = os.path.join(g_drive, 'base_proteinas_agrupadas_final.csv')
    import glob
    csvs = glob.glob(os.path.join(DIR_CSV_DRIVE, '*.csv'))
    
    if csvs:
        with open(ARQUIVO_FINAL, 'w', encoding='utf-8') as f_out:
            f_out.write('Arquivo_Origem;Grupo_Similaridade;ID_da_Proteina;Tipo_Nutricional\n')
            total_csvs = len(csvs)
            for i, csv_file in enumerate(csvs, 1):
                with open(csv_file, 'r', encoding='utf-8') as f_in:
                    next(f_in) # pula cabecalho
                    for line in f_in:
                        f_out.write(line)
                
                # Avisa no log a cada 100 arquivos mesclados para atualizar mais rápido na tela
                if i % 100 == 0 or i == total_csvs:
                    logging.info(f"Progresso da mesclagem: {i} de {total_csvs} arquivos unidos...")
        
        logging.info("Mesclagem concluída com sucesso! Arquivo final gerado.")
        
        # VALIDAÇÃO
        total_esperado = len(arquivos_gz)
        if total_csvs == total_esperado:
            logging.info(f"VALIDAÇÃO OK: Sucesso absoluto! Todos os {total_esperado} arquivos da base original foram inseridos no CSV final.")
        else:
            logging.warning(f"ATENÇÃO: A base original tem {total_esperado} arquivos, mas apenas {total_csvs} foram mesclados. Pode haver arquivos corrompidos que foram pulados.")
    else:
        logging.info("Nenhum CSV encontrado para mesclar.")

if __name__ == "__main__":
    iniciar_automacao()