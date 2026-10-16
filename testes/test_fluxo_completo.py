"""Integração em diretórios temporários.

MMseqs2, ESM-2 e treino são substituídos explicitamente neste teste.
Leitura de GZ, rótulos, geração dos lotes, auditoria, consolidação, partições
e registro SQLite usam o código real. Não é uma avaliação biológica.
"""
import contextlib
import csv
import gzip
import io
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from test_sistema_tcc import BaseTeste, ORIGEM, salvar
from sistema_tcc.core import Catalogo, Executor, Store, sha
from sistema_tcc.fluxo import Fluxo, Pausado, fasta_limitado


def instalar_scripts(root):
    for name in ('preparar_base_ia.py','validar_base_embeddings.py','treinar_classificador_gpu.py','processar_base_gpu.py'):
        origem=ORIGEM/'etapas'/name
        shutil.copyfile(origem,root/'etapas'/name)
    origem=ORIGEM/'piloto_esm_gpu.py'
    shutil.copyfile(origem,root/'piloto_esm_gpu.py')


def fonte_teste(pasta):
    lines=[]
    for i in range(120):
        seq=('HILKMFTWV' if i%2==0 else 'ACDEG')+'A'*(i+1)
        lines.append(f'>NCBI_TESTE_{i}.1\n{seq}\n')
    payload=gzip.compress(''.join(lines).encode())
    p=pasta/'proteinas.zip'
    with zipfile.ZipFile(p,'w') as z:
        z.writestr('proteinas/teste.fsa_aa.gz',payload)
    return p


class FluxoFixture(Fluxo):
    def mmseqs_inicial(self):
        # Agrupamento simulado: cada sequência é representante de um grupo.
        n=self.meta('entrada')['quantidade'];dest=self.pasta/'mmseqs_inicial';dest.mkdir()
        tsv=dest/'inicial_cluster.tsv'
        tsv.write_text(''.join(f'p{i:09d}\tp{i:09d}\n' for i in range(n)))
        with self.db() as db:
            db.execute('UPDATE proteinas SET grupo_inicial=uid')
        r={'ok':True,'tipo':'agrupamento_inicial_mmseqs2','representantes':n,'proteinas_entrada':n,
            'teste_simulado':True}
        salvar(dest/'relatorio.json',r);self.meta('mmseqs_inicial',r,True)
        return r,[dest/'relatorio.json',tsv]

    def script(self,nome,*args):
        import numpy as np
        p=self.modulo('etapas/'+nome)
        if nome=='processar_base_gpu.py':
            piloto=self.modulo('piloto_esm_gpu.py')
            def fake_embeddings(*a):
                rows=a[-1]
                x=np.array([[float(j in range(len(r['sequencia'])%20)) for j in range(320)] for r in rows],dtype=np.float32)
                return x,{'segundos_embeddings_apos_aquecimento':0.0,'teste_simulado':True}
            with patch.object(piloto,'exigir_gpu',return_value=(None,None,None,None,{'teste_simulado':True})),patch.object(piloto,'gerar_embeddings',side_effect=fake_embeddings),patch.dict(sys.modules,{'piloto_esm_gpu':piloto}):
                exigir_codigo=p.main(list(map(str,args)))
        else:
            exigir_codigo=p.main(list(map(str,args)))
        if exigir_codigo!=0:
            raise AssertionError(f'{nome} falhou: {exigir_codigo}')

    def agrupar(self):
        p=self.modulo('etapas/preparar_base_ia.py')
        r=json.loads((self.pasta/'base/relatorio_consolidacao.json').read_text())
        dest=self.pasta/'grupos';dest.mkdir()
        tsv=dest/'global_cluster.tsv';n=self.n()
        tsv.write_text(''.join(f'p{i:09d}\tp{i:09d}\n' for i in range(n)))
        r={'ok':True,'tipo':'agrupamento_global_mmseqs2','base':str(self.pasta/'base'),'proteinas':n,
            'grupos':n,'maior_grupo':1,'fasta_sha256':r['hashes_arquivos']['sequencias.fasta'],'tsv_sha256':sha(tsv),
            'parametros':{'identidade_minima':.5,'cobertura_minima':.8,'cov_mode':0,'cluster_mode':1,
                'alignment_mode':3,'kmer_per_seq':80,'evalue':.001},'teste_simulado':True}
        salvar(dest/'relatorio_agrupamento.json',r)
        return {'grupos':n},[dest/'relatorio_agrupamento.json',tsv]

    def treinar(self):
        dest=self.pasta/'modelo';dest.mkdir()
        (dest/'modelo.pt').write_text('MODELO SIMULADO APENAS PARA TESTAR O CONTROLADOR')
        (dest/'historico.csv').write_text('epoca;score\n1;0.5\n')
        (dest/'predicoes_teste.csv').write_text('uid;predicao\n')
        salvar(dest/'configuracao.json',{'teste_simulado':True})
        base=self.pasta/'base/relatorio_consolidacao.json';part=self.pasta/'particoes/relatorio_particoes.json'
        s=json.loads(part.read_text());n=s['particoes']['teste']['proteinas']
        r={'ok':True,'tipo':'treino_classificador_regra_aa_esm2','treinamento_realizado':True,
            'esm2_retreinado':False,'arquitetura':[320,64,2],'classes':['Incompleta','Completa'],
            'melhor_epoca':1,'teste_mlp':{'proteinas':n,'acuracia':.5,'acuracia_balanceada':.5,'f1_macro':.5},
            'proveniencia':{'base':str(self.pasta/'base'),'particoes':str(self.pasta/'particoes'),
                'relatorio_consolidacao_sha256':sha(base),'relatorio_particoes_sha256':sha(part)},'teste_simulado':True}
        salvar(dest/'relatorio_treino.json',r)
        return {'teste_simulado':True},[dest/'relatorio_treino.json',dest/'modelo.pt']


class FluxoTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.b=BaseTeste(self.root);instalar_scripts(self.root)
        fonte_teste(self.b.p['fontes'][0]);self.store=Store(self.b.p['sistema'])
        self.ex=Executor(self.b.c,self.store,Catalogo(self.b.c,self.store))

    def tearDown(self):
        self.tmp.cleanup()

    def test_fluxo_de_gz_a_banco_e_particoes(self):
        r=self.ex.iniciar_fluxo(1000)
        row,m=self.ex.execucoes.obter(r['execucao'])
        with contextlib.redirect_stdout(io.StringIO()):
            out=FluxoFixture(self.root,Path(row['pasta'])).executar()
        self.assertTrue(out['ok']);self.assertEqual(out['candidatos'],120)
        status=self.ex.execucoes.status(r['execucao'])
        self.assertTrue(all(x['estado']=='concluido' for x in status['fases']))
        with contextlib.closing(sqlite3.connect(status['banco'])) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM proteinas WHERE particao IS NOT NULL').fetchone()[0],120)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM experimentos').fetchone()[0],1)
        cat,c=self.ex.catalogo_execucao(r['execucao'])
        self.assertTrue(all(x['estado']=='concluido' for x in cat.refresh(True).values()))
        self.assertEqual(c.esperado,120)
        self.assertEqual(len(self.ex.execucoes.proteinas(r['execucao'],'NCBI_TESTE_0.1')),1)
        self.assertTrue(self.b.paths['treinar'].is_file())
        # Retomar uma execução concluída só confere saídas: não volta a chamar o treino.
        fluxo=FluxoFixture(self.root,Path(row['pasta']))
        with patch.object(fluxo,'treinar',side_effect=AssertionError('Não repetir treino')),contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(fluxo.executar()['ok'])

    def test_pausa_e_retomada_preservam_entrada(self):
        r=self.ex.iniciar_fluxo(1000);row,_=self.ex.execucoes.obter(r['execucao'])
        fluxo=FluxoFixture(self.root,Path(row['pasta']))
        with contextlib.redirect_stdout(io.StringIO()):
            fluxo.etapa('extrair',fluxo.extrair)
            self.ex.controles(pausado=True)
            with self.assertRaises(Pausado):
                fluxo.etapa('mmseqs_inicial',fluxo.mmseqs_inicial)
            self.ex.controles(pausado=False)
            with patch.object(fluxo,'extrair',side_effect=AssertionError('Não reler GZ')):
                self.assertTrue(fluxo.executar()['ok'])

    def test_representantes_reduzem_base_sem_perder_membros_no_banco(self):
        class Reduzido(FluxoFixture):
            def mmseqs_inicial(s):
                n=s.meta('entrada')['quantidade'];dest=s.pasta/'mmseqs_inicial';dest.mkdir()
                tsv=dest/'inicial_cluster.tsv';grupos=[i-(2 if i%4>=2 else 0) for i in range(n)]
                tsv.write_text(''.join(f'p{r:09d}\tp{i:09d}\n' for i,r in enumerate(grupos)))
                with s.db() as db:
                    db.executemany('UPDATE proteinas SET grupo_inicial=? WHERE uid=?',[(f'p{r:09d}',f'p{i:09d}') for i,r in enumerate(grupos)])
                r={'ok':True,'representantes':len(set(grupos)),'teste_simulado':True}
                salvar(dest/'relatorio.json',r);s.meta('mmseqs_inicial',r,True)
                return r,[dest/'relatorio.json',tsv]
        r=self.ex.iniciar_fluxo(1000);row,_=self.ex.execucoes.obter(r['execucao'])
        with contextlib.redirect_stdout(io.StringIO()):
            out=Reduzido(self.root,Path(row['pasta'])).executar()
        self.assertEqual(out['candidatos'],120);self.assertEqual(out['representantes_com_embedding'],60)
        with contextlib.closing(sqlite3.connect(out['banco'])) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM proteinas').fetchone()[0],120)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM proteinas WHERE indice_embedding IS NOT NULL').fetchone()[0],60)

    def test_inventario_zip_e_fonte_individual(self):
        fontes=self.ex.execucoes.inventario()
        self.assertEqual(len(fontes),1)
        r=self.ex.iniciar_fluxo(1000,fontes[0]['id'])
        _,m=self.ex.execucoes.obter(r['execucao'])
        self.assertEqual(m['fontes'][0]['membro'],'proteinas/teste.fsa_aa.gz')
        self.assertEqual(m['epocas'],10)
        with self.assertRaises(ValueError):
            self.ex.iniciar_fluxo(1000,'../../arbitrario.gz')

    def test_alteracao_fontes_e_codigo_sao_bloqueadas(self):
        r=self.ex.iniciar_fluxo(1000);row,m=self.ex.execucoes.obter(r['execucao'])
        path=Path(m['fontes'][0]['arquivo']);path.write_bytes(path.read_bytes()+b'x')
        fluxo=FluxoFixture(self.root,Path(row['pasta']))
        with self.assertRaises(ValueError),contextlib.redirect_stdout(io.StringIO()):
            fluxo.extrair()
        script=Path(row['pasta'])/'codigo/piloto_esm_gpu.py'
        script.write_text('codigo alterado')
        with self.assertRaises(ValueError):
            FluxoFixture(self.root,Path(row['pasta']))

    def test_parser_limita_memoria_e_normaliza_stops(self):
        r=list(fasta_limitado(io.StringIO('>a\nHILKMFTWV**\n>b\nAC*DE\n>c\n'+'A'*20000+'\n')))
        self.assertEqual(r[0][1],'HILKMFTWV');self.assertTrue(r[0][3])
        self.assertFalse(r[1][3]);self.assertEqual(len(r[2][1]),512)
        self.assertEqual(r[2][2],20000)


if __name__=='__main__':
    unittest.main()
