"""Testes do histórico transacional em SQLite (Fase D1).

Cobrem gravação atômica, substituição de mensagens, metadados de
governança/proveniência, exclusão em cascata, limpeza em lote, cache
de folhas CIM e migração aditiva do histórico JSON legado. Nenhum
teste usa o banco real do usuário: cada caso cria um arquivo em
``build/_tmp_history_db`` e apaga no final.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from services import db_service, history_db

RAIZ = Path(__file__).resolve().parent.parent
BASE_TESTES = RAIZ / "build" / "_tmp_history_db"


def preparar_pasta(nome):
    """Pasta de teste isolada, limpa antes de cada caso."""

    caminho = BASE_TESTES / nome
    shutil.rmtree(caminho, ignore_errors=True)
    caminho.mkdir(parents=True, exist_ok=True)

    return caminho


class BaseHistorico(unittest.TestCase):
    """Base com banco temporário e mensagens de exemplo."""

    def setUp(self):
        self._pasta = preparar_pasta(self._testMethodName)
        self.addCleanup(shutil.rmtree, self._pasta, ignore_errors=True)
        self.db = self._pasta / "memoria.db"
        db_service.inicializar_banco(self.db)

    def mensagens(self):
        """Duas mensagens com governança, proveniência e fontes."""

        return [
            {
                "role": "user",
                "content": "Ouro no Canadá",
                "chave": 0,
            },
            {
                "role": "assistant",
                "content": "Resposta técnica.",
                "chave": 1,
                "workflow": "triagem_area",
                "governanca": {
                    "veredito": "PASS",
                    "motivo": "Contrato válido.",
                    "afirmacoes": [
                        {
                            "texto": "Há ouro.",
                            "classificacao": "OBSERVED",
                            "evidence_id": "ev_1",
                        },
                    ],
                },
                "proveniencia": [
                    {
                        "source_type": "RIGeo / SGB",
                        "locator": "https://exemplo.test/a",
                        "retrieved_at": "2026-01-01T00:00:00-04:00",
                        "origem": "cache",
                    },
                ],
                "artigos_rigeo": [
                    {"titulo": "A", "link": "https://exemplo.test/a"},
                ],
            },
        ]


class TestGravacaoERecuperacao(BaseHistorico):
    """Round-trip da conversa, metadados e substituição atômica."""

    def test_grava_e_recupera_com_metadados_de_governanca(self):
        salvo = history_db.salvar_conversa(
            "sessao_1",
            "",
            self.mensagens(),
            workflow="triagem_area",
            folha_cim="SB.21",
            caminho_db=self.db,
        )

        self.assertTrue(salvo)

        conversa = history_db.carregar_conversa("sessao_1", self.db)

        self.assertEqual(conversa["id"], "sessao_1")
        self.assertEqual(conversa["titulo"], "Ouro no Canadá")
        self.assertEqual(conversa["workflow"], "triagem_area")
        self.assertEqual(conversa["folha_cim"], "SB.21")
        self.assertEqual(len(conversa["mensagens"]), 2)

        # A chave de widget é recalculada na leitura; não vai ao banco.
        self.assertNotIn("chave", conversa["mensagens"][0])
        self.assertEqual(conversa["mensagens"][0]["role"], "user")

        assistente = conversa["mensagens"][1]
        self.assertEqual(assistente["role"], "assistant")
        self.assertEqual(
            assistente["governanca"]["veredito"],
            "PASS",
        )
        self.assertEqual(
            assistente["proveniencia"][0]["origem"],
            "cache",
        )
        self.assertEqual(
            assistente["artigos_rigeo"][0]["titulo"],
            "A",
        )

        linhas = db_service.listar_mensagens("sessao_1", caminho_db=self.db)
        self.assertEqual(linhas[1]["veredito"], "PASS")

    def test_segunda_gravacao_substitui_sem_duplicar(self):
        history_db.salvar_conversa(
            "sessao_2",
            "Título",
            self.mensagens(),
            caminho_db=self.db,
        )
        history_db.salvar_conversa(
            "sessao_2",
            "Título",
            self.mensagens()[:1],
            caminho_db=self.db,
        )

        linhas = db_service.listar_mensagens("sessao_2", caminho_db=self.db)

        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0]["papel"], "user")

    def test_conversa_sem_mensagens_remove_a_sessao(self):
        history_db.salvar_conversa(
            "sessao_3",
            "Título",
            self.mensagens(),
            caminho_db=self.db,
        )

        self.assertFalse(
            history_db.salvar_conversa(
                "sessao_3",
                "Título",
                [],
                caminho_db=self.db,
            )
        )
        self.assertIsNone(
            history_db.carregar_conversa("sessao_3", self.db)
        )

    def test_papel_invalido_nao_grava_nada(self):
        history_db.salvar_conversa(
            "sessao_4",
            "Título",
            self.mensagens(),
            caminho_db=self.db,
        )

        with self.assertRaises(ValueError):
            db_service.substituir_conversa(
                "sessao_4",
                "Título",
                [{"role": "tool", "content": "x"}],
                caminho_db=self.db,
            )

        linhas = db_service.listar_mensagens("sessao_4", caminho_db=self.db)
        self.assertEqual(len(linhas), 2)


class TestListagemEExclusao(BaseHistorico):
    """Lista, exclusão em cascata e limpeza em lote."""

    def test_lista_conversas_com_workflow_e_folha(self):
        history_db.salvar_conversa(
            "sessao_5",
            "Conversa A",
            self.mensagens(),
            workflow="hidrogeologia",
            folha_cim="SC.22",
            caminho_db=self.db,
        )

        conversas = history_db.listar_conversas(caminho_db=self.db)

        self.assertEqual(len(conversas), 1)
        self.assertEqual(conversas[0]["titulo"], "Conversa A")
        self.assertEqual(conversas[0]["workflow"], "hidrogeologia")
        self.assertEqual(conversas[0]["folha_cim"], "SC.22")
        self.assertEqual(conversas[0]["total_mensagens"], 2)

    def test_exclusao_remove_mensagens_vinculos_e_afirmacoes(self):
        db_service.criar_sessao("sessao_6", "Teste", caminho_db=self.db)
        mensagem_id = db_service.adicionar_mensagem(
            "sessao_6",
            "assistant",
            "Texto",
            caminho_db=self.db,
        )
        db_service.registrar_evidencia(
            "ev_6",
            titulo="Fonte",
            caminho_db=self.db,
        )
        db_service.vincular_evidencia(
            mensagem_id,
            "ev_6",
            caminho_db=self.db,
        )
        db_service.registrar_afirmacao(
            mensagem_id,
            "Há ouro.",
            "OBSERVED",
            evidence_id="ev_6",
            caminho_db=self.db,
        )

        self.assertTrue(history_db.excluir_conversa("sessao_6", self.db))

        self.assertEqual(
            db_service.listar_mensagens("sessao_6", caminho_db=self.db),
            [],
        )

        with db_service.conexao(self.db) as conexao_sqlite:
            afirmacoes = conexao_sqlite.execute(
                "SELECT COUNT(*) AS total FROM claim_records"
            ).fetchone()["total"]
            vinculos = conexao_sqlite.execute(
                "SELECT COUNT(*) AS total FROM message_evidence"
            ).fetchone()["total"]

        self.assertEqual(afirmacoes, 0)
        self.assertEqual(vinculos, 0)

    def test_exclusao_total_devolve_quantidade(self):
        for indice in (1, 2):
            history_db.salvar_conversa(
                f"sessao_{indice}",
                f"Conversa {indice}",
                self.mensagens(),
                caminho_db=self.db,
            )

        self.assertEqual(
            history_db.excluir_todas_conversas(self.db),
            2,
        )
        self.assertEqual(history_db.listar_conversas(caminho_db=self.db), [])

    def test_cache_de_folhas_cim_conta_folhas_distintas(self):
        db_service.salvar_cache_espacial(
            "SB.21",
            {"x": 1},
            caminho_db=self.db,
        )
        db_service.salvar_cache_espacial(
            "SB.21",
            {"x": 2},
            fonte="outra",
            caminho_db=self.db,
        )
        db_service.salvar_cache_espacial(
            "SC.22",
            {"x": 3},
            caminho_db=self.db,
        )

        self.assertEqual(history_db.contar_folhas_cache(self.db), 2)


class TestMigracaoLegado(BaseHistorico):
    """Importação aditiva do JSON de data/historico, sem apagar nada."""

    def test_migra_uma_vez_e_preserva_os_arquivos(self):
        pasta = self._pasta / "historico"
        pasta.mkdir(parents=True)
        arquivo = pasta / "20260101_000000_abcd1234.json"
        arquivo.write_text(
            json.dumps(
                {
                    "versao": 1,
                    "id": "20260101_000000_abcd1234",
                    "titulo": "Conversa legada",
                    "criado_em": "2026-01-01T00:00:00-04:00",
                    "atualizado_em": "2026-01-01T00:10:00-04:00",
                    "mensagens": [
                        {"role": "user", "content": "Pergunta"},
                        {
                            "role": "assistant",
                            "content": "Resposta legada",
                            "fonte": "sgb",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        migradas = history_db.migrar_historico_json(
            diretorio=pasta,
            caminho_db=self.db,
            forcar=True,
        )

        self.assertEqual(migradas, 1)
        self.assertTrue(arquivo.is_file())

        conversa = history_db.carregar_conversa(
            "20260101_000000_abcd1234",
            self.db,
        )
        self.assertEqual(conversa["titulo"], "Conversa legada")
        self.assertEqual(conversa["mensagens"][1]["fonte"], "sgb")

        # Repetir não duplica: o session_id já existe no banco.
        self.assertEqual(
            history_db.migrar_historico_json(
                diretorio=pasta,
                caminho_db=self.db,
                forcar=True,
            ),
            0,
        )

    def test_arquivo_invalido_e_ignorado(self):
        pasta = self._pasta / "historico"
        pasta.mkdir(parents=True)
        (pasta / "invalido.json").write_text(
            "{ nao e json",
            encoding="utf-8",
        )

        self.assertEqual(
            history_db.migrar_historico_json(
                diretorio=pasta,
                caminho_db=self.db,
                forcar=True,
            ),
            0,
        )


class TestTraducaoDeErrosELimites(unittest.TestCase):
    """Falhas de SQLite viram HistoricoBDError e o modo de teste isola a migração."""

    def setUp(self):
        self._pasta = preparar_pasta(self._testMethodName)
        self.addCleanup(shutil.rmtree, self._pasta, ignore_errors=True)
        self.db = self._pasta / "memoria.db"
        db_service.inicializar_banco(self.db)

    def test_listagem_traduz_sqlite_error(self):
        with mock.patch.object(
            db_service,
            "listar_sessoes",
            side_effect=sqlite3.OperationalError("banco indisponível"),
        ), self.assertRaises(history_db.HistoricoBDError):
            history_db.listar_conversas(caminho_db=self.db)

    def test_migracao_traduz_sqlite_error(self):
        with mock.patch.object(
            history_db,
            "_ler_migracao",
            side_effect=sqlite3.OperationalError("schema indisponível"),
        ), self.assertRaises(history_db.HistoricoBDError):
            history_db.migrar_historico_json(
                diretorio=self._pasta,
                caminho_db=self.db,
            )

    def test_modo_de_teste_pula_a_migracao_na_inicializacao_padrao(self):
        historico = self._pasta / "historico"
        historico.mkdir()
        (historico / "legado.json").write_text(
            json.dumps(
                {
                    "id": "sessao_legada",
                    "titulo": "Legado",
                    "mensagens": [
                        {"role": "user", "content": "Pergunta"},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with mock.patch.dict(
            os.environ,
            {
                "NEXUSGEO_DB_PATH": str(self.db),
                "NEXUSGEO_TEST_MODE": "1",
            },
            clear=False,
        ), mock.patch(
            "services.history_service.DIRETORIO_HISTORICO",
            historico,
        ):
            caminho = history_db.inicializar()

        self.assertEqual(caminho, self.db.resolve())
        self.assertEqual(
            history_db.listar_conversas(caminho_db=self.db),
            [],
        )


if __name__ == "__main__":
    unittest.main()