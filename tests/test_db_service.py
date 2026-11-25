"""Testes unitários da persistência SQLite das três camadas (D1).

Cobrem schema, WAL, foreign_keys, cascata de exclusão, resumo
progressivo, cache espacial e índice de documentos por SHA-256. Nenhum
teste abre a interface, acessa a rede ou usa o banco real do usuário:
cada caso cria um arquivo temporário próprio.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from services import db_service

RAIZ = Path(__file__).resolve().parent.parent
BASE_TESTES = RAIZ / "build" / "_tmp_db_service"


def preparar_pasta(nome):
    """Pasta de teste dentro do projeto, limpa antes de cada caso."""

    caminho = BASE_TESTES / nome
    shutil.rmtree(caminho, ignore_errors=True)
    caminho.mkdir(parents=True, exist_ok=True)

    return caminho


class BaseBancoTemporario(unittest.TestCase):
    """Base com banco em pasta temporária e schema já criado."""

    def setUp(self):
        self._pasta = preparar_pasta(self._testMethodName)
        self.addCleanup(
            shutil.rmtree,
            self._pasta,
            ignore_errors=True,
        )
        self.db = self._pasta / "memoria.db"
        db_service.inicializar_banco(self.db)

    def contar(self, tabela):
        """Conta linhas de uma tabela no banco de teste."""

        with db_service.conexao(self.db) as conexao:
            linha = conexao.execute(
                f"SELECT COUNT(*) AS total FROM {tabela}"
            ).fetchone()

        return int(linha["total"])


class TestSchemaEWal(BaseBancoTemporario):
    """Configuração do arquivo e presença das tabelas das três camadas."""

    def test_tabelas_das_tres_camadas_existem(self):
        esperadas = {
            "chat_sessions",
            "chat_messages",
            "evidence_sources",
            "message_evidence",
            "claim_records",
            "spatial_cache",
            "documents",
            "schema_meta",
        }

        with db_service.conexao(self.db) as conexao:
            encontradas = {
                linha["name"]
                for linha in conexao.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table'"
                ).fetchall()
            }

        self.assertTrue(esperadas.issubset(encontradas))
        self.assertEqual(self.contar("schema_meta"), 1)

    def test_wal_foreign_keys_e_busy_timeout(self):
        with db_service.conexao(self.db) as conexao:
            modo = conexao.execute("PRAGMA journal_mode").fetchone()[0]
            fk = conexao.execute("PRAGMA foreign_keys").fetchone()[0]
            busy = conexao.execute("PRAGMA busy_timeout").fetchone()[0]

        self.assertEqual(str(modo).lower(), "wal")
        self.assertEqual(int(fk), 1)
        self.assertGreaterEqual(int(busy), 5000)

    def test_inicializacao_e_idempotente(self):
        db_service.inicializar_banco(self.db)
        db_service.inicializar_banco(self.db)

        self.assertEqual(self.contar("chat_sessions"), 0)


class TestCascataEpisodica(BaseBancoTemporario):
    """Exclusão de sessão deve limpar mensagens, vínculos e claims."""

    def test_delete_cascade_remove_filhos_e_preserva_evidencia(self):
        sessao = db_service.criar_sessao(
            "sessao_cascata",
            "Cascata",
            caminho_db=self.db,
        )
        mensagem = db_service.adicionar_mensagem(
            sessao,
            "assistant",
            "O granito é observado na área.",
            caminho_db=self.db,
        )
        evidencia = db_service.registrar_evidencia(
            "ev_cascata",
            tipo="documento",
            titulo="Mapa geológico",
            caminho_db=self.db,
        )
        db_service.vincular_evidencia(
            mensagem,
            evidencia,
            caminho_db=self.db,
        )
        db_service.registrar_afirmacao(
            mensagem,
            "O granito é observado.",
            "OBSERVED",
            evidence_id=evidencia,
            caminho_db=self.db,
        )

        self.assertTrue(db_service.excluir_sessao(sessao, self.db))

        self.assertEqual(self.contar("chat_sessions"), 0)
        self.assertEqual(self.contar("chat_messages"), 0)
        self.assertEqual(self.contar("message_evidence"), 0)
        self.assertEqual(self.contar("claim_records"), 0)
        self.assertEqual(self.contar("evidence_sources"), 1)

    def test_observed_sem_evidencia_e_recusado(self):
        sessao = db_service.criar_sessao(
            "sessao_claim",
            caminho_db=self.db,
        )
        mensagem = db_service.adicionar_mensagem(
            sessao,
            "assistant",
            "Resposta",
            caminho_db=self.db,
        )

        with self.assertRaises(ValueError):
            db_service.registrar_afirmacao(
                mensagem,
                "Afirmação sem fonte",
                "OBSERVED",
                caminho_db=self.db,
            )

    def test_check_do_schema_tambem_bloqueia_observed_sem_evidencia(self):
        sessao = db_service.criar_sessao(
            "sessao_check",
            caminho_db=self.db,
        )
        mensagem = db_service.adicionar_mensagem(
            sessao,
            "assistant",
            "Resposta",
            caminho_db=self.db,
        )

        with db_service.conexao(self.db) as conexao, self.assertRaises(
            sqlite3.IntegrityError
        ):
            conexao.execute(
                """
                INSERT INTO claim_records (
                    id, message_id, texto, classificacao,
                    evidence_id, criado_em
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "cl_invalida",
                    mensagem,
                    "Sem fonte",
                    "OBSERVED",
                    None,
                    db_service.agora_iso(),
                ),
            )


class TestResumoProgressivo(BaseBancoTemporario):
    """Sessão guarda resumo, cobertura e ordem das mensagens."""

    def test_resumo_e_marcacao_de_mensagens(self):
        sessao = db_service.criar_sessao(
            "sessao_resumo",
            "Resumo",
            caminho_db=self.db,
        )

        primeira = db_service.adicionar_mensagem(
            sessao, "user", "Pergunta um", caminho_db=self.db
        )
        segunda = db_service.adicionar_mensagem(
            sessao, "assistant", "Resposta um", caminho_db=self.db
        )

        self.assertGreater(segunda, primeira)
        self.assertTrue(
            db_service.atualizar_resumo_sessao(
                sessao,
                "Resumo rolling",
                ate_sequencia=1,
                caminho_db=self.db,
            )
        )

        dados = db_service.obter_sessao(sessao, self.db)

        self.assertEqual(dados["resumo"], "Resumo rolling")
        self.assertEqual(dados["resumo_ate_sequencia"], 1)
        self.assertEqual(dados["total_mensagens"], 2)

        self.assertEqual(
            db_service.marcar_mensagens_resumidas(
                sessao, 1, self.db
            ),
            2,
        )

        mensagens = db_service.listar_mensagens(sessao, caminho_db=self.db)

        self.assertEqual(
            [item["sequencia"] for item in mensagens],
            [0, 1],
        )
        self.assertTrue(all(item["resumida_em"] for item in mensagens))

    def test_mensagem_com_papel_invalido_e_recusada(self):
        sessao = db_service.criar_sessao(
            "sessao_papel",
            caminho_db=self.db,
        )

        with self.assertRaises(ValueError):
            db_service.adicionar_mensagem(
                sessao,
                "tool",
                "conteúdo",
                caminho_db=self.db,
            )


class TestCacheEDocumentos(BaseBancoTemporario):
    """Camada operacional: cache por folha CIM e índice por hash."""

    def test_cache_espacial_faz_upsert_por_folha_e_fonte(self):
        primeiro = db_service.salvar_cache_espacial(
            "sa.20",
            {"unidades": ["A"]},
            collected_at="2026-01-01T00:00:00-04:00",
            source_version="v1",
            caminho_db=self.db,
        )
        segundo = db_service.salvar_cache_espacial(
            "SA.20",
            {"unidades": ["B"]},
            collected_at="2026-02-01T00:00:00-04:00",
            source_version="v2",
            caminho_db=self.db,
        )

        self.assertEqual(primeiro, segundo)
        self.assertEqual(self.contar("spatial_cache"), 1)

        registros = db_service.obter_cache_espacial("SA.20", caminho_db=self.db)

        self.assertEqual(len(registros), 1)
        self.assertEqual(registros[0]["payload"]["unidades"], ["B"])
        self.assertEqual(registros[0]["source_version"], "v2")

    def test_documento_indexado_por_hash_e_atualizado(self):
        hash_doc = "a" * 64

        db_service.registrar_documento(
            hash_doc,
            nome="mapa.pdf",
            caminho="data/docs/mapa.pdf",
            tamanho=10,
            caminho_db=self.db,
        )
        db_service.registrar_documento(
            hash_doc,
            nome="mapa-novo.pdf",
            tamanho=20,
            caminho_db=self.db,
        )

        documento = db_service.obter_documento_por_hash(
            hash_doc.upper(),
            caminho_db=self.db,
        )

        self.assertIsNotNone(documento)
        self.assertEqual(documento["nome"], "mapa-novo.pdf")
        self.assertEqual(documento["tamanho"], 20)
        self.assertEqual(self.contar("documents"), 1)

    def test_hash_invalido_nao_e_indexado(self):
        with self.assertRaises(ValueError):
            db_service.registrar_documento(
                "abc",
                nome="invalido.txt",
                caminho_db=self.db,
            )

        self.assertIsNone(
            db_service.obter_documento_por_hash("abc", self.db)
        )


class TestResolucaoDeDiretorio(unittest.TestCase):
    """ASSISTENTE_DATA_DIR e LOCALAPPDATA definem o local do banco."""

    def test_assistente_data_dir_tem_prioridade(self):
        pasta = preparar_pasta("resolucao_assistente")
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ["ASSISTENTE_DATA_DIR"] = str(pasta)
            os.environ.pop("NEXUSGEO_DB_PATH", None)

            self.assertEqual(
                db_service.diretorio_dados(),
                pasta.resolve(),
            )
            self.assertEqual(
                db_service.caminho_padrao_banco(),
                pasta.resolve() / "data" / "nexusgeoia.db",
            )

    def test_localappdata_e_o_fallback(self):
        pasta = preparar_pasta("resolucao_localappdata")
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)

        with mock.patch.dict(
            os.environ,
            {"LOCALAPPDATA": str(pasta)},
            clear=False,
        ):
            os.environ.pop("ASSISTENTE_DATA_DIR", None)
            os.environ.pop("NEXUSGEO_DB_PATH", None)

            self.assertEqual(
                db_service.diretorio_dados(),
                pasta.resolve() / "NexusGeoIA",
            )

    def test_resumo_memoria_conta_as_camadas(self):
        pasta = preparar_pasta("resolucao_resumo")
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        caminho = pasta / "memoria.db"
        db_service.inicializar_banco(caminho)

        resumo = db_service.resumo_memoria(caminho)

        self.assertEqual(resumo["journal_mode"], "wal")
        self.assertEqual(resumo["sessoes"], 0)
        self.assertEqual(resumo["documentos"], 0)


class TestHardeningConexao(unittest.TestCase):
    """Falha de PRAGMA fecha a conexão antes de sair de conectar()."""

    def test_operational_error_no_pragma_fecha_a_conexao(self):
        class ConexaoFalsa:
            row_factory = None

            def __init__(self):
                self.fechada = False

            def execute(self, _sql):
                raise sqlite3.OperationalError("PRAGMA recusado")

            def close(self):
                self.fechada = True

        pasta = preparar_pasta("pragma_falha")
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        falsa = ConexaoFalsa()

        with mock.patch.object(
            db_service.sqlite3,
            "connect",
            return_value=falsa,
        ), self.assertRaises(sqlite3.OperationalError):
            db_service.conectar(pasta / "memoria.db")

        self.assertTrue(falsa.fechada)


if __name__ == "__main__":
    unittest.main()
