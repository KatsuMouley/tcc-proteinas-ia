# ESM-2 na GTX 1650

Este pacote verifica o ESM-2 pequeno na GPU do seu computador. Usa o mesmo
modelo e a mesma revisao do teste CPU que voce concluiu:
`facebook/esm2_t6_8M_UR50D`, revisao
`c731040fcd8d73dceaa04b0a8e6329b345b0f5df`.

O teste usa uma sequencia sintetica de 20 aminoacidos, gera um vetor de 320
valores e nao realiza treinamento nem modifica sua base biologica.

## Executar

1. Extraia os tres arquivos do ZIP diretamente em `C:\ai_tcc`, ao lado de
   `.venv`, `testar_esm.py` e `cache`. Evite deixar os arquivos dentro de uma
   subpasta adicional. O teste CPU existente pode continuar na mesma pasta.
2. No PowerShell dessa pasta, execute primeiro o teste:

   ```powershell
   .\.venv\Scripts\python.exe .\testar_esm_gpu.py
   ```

3. Se `cuda_compilada` aparecer como `null`, o PyTorch instalado e para CPU.
   Quando os demais scripts Python desse ambiente tiverem terminado, execute:

   ```powershell
   .\setup_gpu.cmd
   ```

   O instalador salva a lista inicial de pacotes em `requirements_antes_gpu.txt`,
   instala PyTorch 2.9.1 com CUDA 12.6, confere dependencias e executa o teste GPU.
   Esse pacote tem distribuicao oficial para Python 3.13 de 64 bits no Windows.
   O instalador nao instala ou altera o driver NVIDIA.

4. Se CUDA ja aparece compilada, mas continua indisponivel, execute `nvidia-smi`
   e envie esse resultado junto com o JSON do teste para diagnosticar o driver.

## Resultado esperado

O JSON deve conter `ok: true`, `dispositivo: "cuda:0"`, o nome da GTX 1650,
`dimensao_embedding: 320` e `treinamento_realizado: false`.

O teste valida uma operacao CUDA real, alem de consultar `is_available()`,
e exige que tanto o modelo quanto o embedding estejam na GPU. Se CUDA
falhar, ele termina com erro e nao executa uma alternativa na CPU.

## Cache e consumo de recursos

- Por padrao usa `C:\ai_tcc\cache\huggingface` e somente os arquivos locais.
  Nao baixa novamente o modelo. Se faltar algum componente ou a revisao,
  mostra erro. Para um cache diferente, acrescente `--cache "CAMINHO"`.
- Para autorizar o download de componentes ausentes, acrescente
  `--permitir-download` ao comando do teste.
- Limita o PyTorch a duas threads de CPU e usa um lote de uma sequencia,
  em float32, com gradientes desativados. Esse limite de threads aplica-se
  somente a esse processo; nao reserva nucleos nem impoe um teto percentual.
- O tempo de inferencia e medido depois de um aquecimento. Esse teste curto
  comprova funcionamento; nao mede a vantagem de desempenho com sua base.
- A memoria mostrada no JSON e a memoria de GPU alocada pelo PyTorch neste
  teste, e nao a RAM do PC nem o consumo total dos outros programas.
- Os avisos sobre symlinks e falta de `hf_xet` no teste anterior nao impediram
  seu download e sua inferencia. Nao e preciso executar o teste como administrador.

Instalar CUDA no PyTorch nao muda automaticamente os outros scripts. Para
usar GPU, cada etapa ESM-2 precisa mover o modelo e as entradas para `cuda`
e aplicar os limites de CPU. A extracao FASTA e o agrupamento `mmseqs cluster`
continuam sendo etapas de CPU. Este pacote nao altera os scripts anteriores.

## Fontes oficiais

- [Pacotes PyTorch CUDA 12.6](https://download.pytorch.org/whl/cu126/torch/)
- [Modelo ESM-2 pequeno](https://huggingface.co/facebook/esm2_t6_8M_UR50D)
- [Diagnostico CUDA no PyTorch](https://docs.pytorch.org/docs/stable/generated/torch.cuda.is_available.html)
- [Guia MMseqs2](https://www.mmseqs.com/latest/userguide.pdf)
