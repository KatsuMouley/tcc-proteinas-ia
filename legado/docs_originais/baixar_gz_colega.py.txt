import os
import sys
from ftplib import FTP
from concurrent.futures import ThreadPoolExecutor

# --- CONFIGURAÇÕES ---
g_drive = r"G:\Meu Drive\base_genes_tcc"
PASTA_DESTINO = os.path.join(g_drive, "arquivos_gz")

os.makedirs(PASTA_DESTINO, exist_ok=True)

# Defina quantas conexões paralelas quer abrir. 10 a 15 é um número excelente e seguro para o NCBI.
MAX_THREADS = 15

def baixar_arquivo_individual(nome_arquivo, idx, total):
    """
    Função executada por cada Thread de forma paralela para baixar um único arquivo.
    """
    caminho_salvamento = os.path.join(PASTA_DESTINO, nome_arquivo)
    
    # Pula se o arquivo já existir localmente
    if os.path.exists(caminho_salvamento):
        # Usamos sys.stdout direto para evitar que prints paralelos se atropelem na mesma linha
        sys.stdout.write(f"⏩ [{idx}/{total}] Já existe: {nome_arquivo}\n")
        sys.stdout.flush()
        return

    try:
        # Cada thread precisa abrir e gerenciar sua própria conexão FTP isolada
        ftp_local = FTP("ftp.ncbi.nlm.nih.gov")
        ftp_local.login()
        ftp_local.cwd("/ncbi-asn1/protein_fasta/")
        
        sys.stdout.write(f"📥 [{idx}/{total}] Iniciando: {nome_arquivo}\n")
        sys.stdout.flush()
        
        with open(caminho_salvamento, "wb") as f_local:
            ftp_local.retrbinary(f"RETR {nome_arquivo}", f_local.write)
            
        sys.stdout.write(f"✨ [{idx}/{total}] Concluído: {nome_arquivo}\n")
        sys.stdout.flush()
        
        ftp_local.quit()
        
    except Exception as e:
        sys.stdout.write(f"❌ Erro no arquivo {nome_arquivo}: {e}\n")
        sys.stdout.flush()

def baixar_base_completa_ftp_paralelo():
        
    print("🌐 Conectando ao servidor FTP para listar a base...")
    
    try:
        # Conexão inicial apenas para mapear a lista de arquivos
        ftp_mestre = FTP("ftp.ncbi.nlm.nih.gov")
        ftp_mestre.login()
        ftp_mestre.cwd("/ncbi-asn1/protein_fasta/")
        
        todos_arquivos = ftp_mestre.nlst()
        arquivos_gz = [f for f in todos_arquivos if f.endswith(".gz")]
        total = len(arquivos_gz)
        
        print(f"📊 Total de arquivos encontrados: {total}")
        print(f"🚀 Ativando motor paralelo com {MAX_THREADS} downloads simultâneos...\n")
        
        ftp_mestre.quit() # Fecha a conexão mestre para liberar o canal
        
        # O ThreadPoolExecutor cria e gerencia a esteira de conexões paralelas
        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            # Envia todos os arquivos para a fila de processamento paralelo
            futures = [
                executor.submit(baixar_arquivo_individual, nome_arquivo, idx, total)
                for idx, nome_arquivo in enumerate(arquivos_gz, start=1)
            ]
            
            # Aguarda todas as tarefas da fila terminarem
            for future in futures:
                future.result()
                
        print("\n🎉 TODOS OS ARQUIVOS FORAM BAIXADOS COM SUCESSO!")
        
    except Exception as e:
        print(f"\n❌ Erro crítico no gerenciador do FTP: {e}")

if __name__ == "__main__":
    # Garante o envio correto de logs sem atraso de buffer no Windows
    sys.stdout.reconfigure(encoding='utf-8')
    baixar_base_completa_ftp_paralelo()