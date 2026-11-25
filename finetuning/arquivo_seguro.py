"""Escrita atômica e idempotente dos artefatos do fine-tuning.

Os artefatos do pacote (dataset JSONL, manifesto, relatórios de
benchmark e auditoria) são material de release: uma falha no meio da
gravação não pode deixar um JSONL truncado nem um manifesto apontando
para um hash que não existe mais. Este módulo concentra a gravação em
arquivo temporário na mesma pasta, com fsync e os.replace, e informa se
o conteúdo realmente mudou — repetir a geração com os mesmos registros
não reescreve bytes idênticos e não altera o mtime do artefato.

A comparação é feita em blocos de 1 MiB, sem carregar uma segunda cópia
integral do arquivo. O módulo não importa banco, rede nem interface,
então a auditoria estática de finetuning.seguranca continua válida.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

TAMANHO_BLOCO = 1024 * 1024


def _temporario(caminho: Path) -> Path:
    """Nome temporário único por processo/thread na mesma pasta."""

    return caminho.with_name(
        f"{caminho.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )


def _conteudo_igual(caminho: Path, conteudo: bytes) -> bool:
    """Compara o arquivo com os bytes novos sem carregar tudo de novo."""

    try:
        if caminho.stat().st_size != len(conteudo):
            return False

        with caminho.open("rb") as arquivo:
            deslocamento = 0

            for bloco in iter(
                lambda: arquivo.read(TAMANHO_BLOCO),
                b"",
            ):
                fim = deslocamento + len(bloco)

                if bloco != conteudo[deslocamento:fim]:
                    return False

                deslocamento = fim

        return deslocamento == len(conteudo)
    except OSError:
        return False


def gravar_bytes_atomico(
    caminho,
    conteudo,
    *,
    forcar: bool = False,
) -> bool:
    """Grava bytes de forma atômica; devolve True quando o arquivo mudou.

    Conteúdo idêntico não é reescrito (forcar=True ignora essa
    verificação). Qualquer falha remove o temporário antes de propagar a
    exceção, então uma interrupção nunca deixa artefato parcial no
    caminho final.
    """

    caminho = Path(caminho)
    dados = bytes(conteudo)

    if not forcar and _conteudo_igual(caminho, dados):
        return False

    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = _temporario(caminho)

    try:
        with temporario.open("wb") as arquivo:
            arquivo.write(dados)
            arquivo.flush()
            os.fsync(arquivo.fileno())

        os.replace(temporario, caminho)
    except BaseException:
        try:
            temporario.unlink(missing_ok=True)
        except OSError:
            pass

        raise

    return True


def gravar_texto_atomico(
    caminho,
    texto,
    *,
    forcar: bool = False,
) -> bool:
    """Versão UTF-8 de :func:`gravar_bytes_atomico`."""

    return gravar_bytes_atomico(
        caminho,
        str(texto).encode("utf-8"),
        forcar=forcar,
    )


def restaurar_bytes(caminho, anterior) -> None:
    """Restaura os bytes anteriores ou remove o arquivo criado agora.

    Usado como rollback quando um segundo artefato (o manifesto do
    dataset) não pôde ser gravado depois do primeiro. anterior=None
    significa que o caminho não existia antes.
    """

    caminho = Path(caminho)

    if anterior is None:
        caminho.unlink(missing_ok=True)
        return

    gravar_bytes_atomico(caminho, anterior, forcar=True)
