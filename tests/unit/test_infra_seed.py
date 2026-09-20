"""El script de seed y las tablas que define la plantilla.

Comprueba que la infraestructura declarada en `template.yaml` soporta de verdad
los datos y las consultas que la aplicación necesita.
"""

import json
import pathlib

import pytest
from moto import mock_aws

SEED_DIR = pathlib.Path(__file__).resolve().parents[2] / "seed"


@pytest.fixture
def aws(monkeypatch):
    from skillpath_common import db

    with mock_aws():
        from tests.fixtures.tables import create_all

        names = create_all()
        for short, full in names.items():
            monkeypatch.setenv(short.upper().replace("-", "_") + "_TABLE", full)
        db.reset_cache()
        yield names
        db.reset_cache()


class TestDatosSemilla:
    def test_hay_un_archivo_de_tarjetas_por_tema(self):
        topics = json.loads((SEED_DIR / "topics.json").read_text(encoding="utf-8"))
        for topic in topics:
            path = SEED_DIR / f"flashcards-{topic['topicId']}.json"
            assert path.exists(), f"falta {path.name}"

    def test_cada_tema_supera_el_umbral_del_quiz(self):
        # Observación #8: el quiz exige 10 conceptos estudiados, así que un
        # mazo con menos de 10 tarjetas jamás podría habilitarlo.
        from skillpath_common.rules import QUIZ_MIN_STUDIED_CONCEPTS

        topics = json.loads((SEED_DIR / "topics.json").read_text(encoding="utf-8"))
        for topic in topics:
            cards = json.loads(
                (SEED_DIR / f"flashcards-{topic['topicId']}.json").read_text(encoding="utf-8")
            )
            assert len(cards) >= QUIZ_MIN_STUDIED_CONCEPTS, topic["topicId"]

    def test_toda_tarjeta_tiene_pregunta_y_respuesta(self):
        for path in SEED_DIR.glob("flashcards-*.json"):
            for card in json.loads(path.read_text(encoding="utf-8")):
                assert card["question"].strip()
                assert card["answer"].strip()

    def test_no_hay_preguntas_repetidas_dentro_de_un_tema(self):
        # Los distractores del quiz salen de otras tarjetas del mismo tema:
        # con preguntas duplicadas podría generarse una opción correcta doble.
        for path in SEED_DIR.glob("flashcards-*.json"):
            preguntas = [c["question"] for c in json.loads(path.read_text(encoding="utf-8"))]
            assert len(preguntas) == len(set(preguntas)), path.name


class TestCargaEnDynamo:
    def test_el_seed_carga_temas_y_tarjetas(self, aws, monkeypatch, capsys):
        monkeypatch.setenv("STAGE", "test")
        monkeypatch.setenv("TOPICS_TABLE", aws["topics"])
        monkeypatch.setenv("FLASHCARDS_TABLE", aws["flashcards"])

        import importlib
        import sys

        sys.path.insert(0, str(SEED_DIR.parent / "scripts"))
        seed = importlib.import_module("seed")
        importlib.reload(seed)
        assert seed.main() == 0

        from skillpath_common.db import table

        topics = table("TOPICS_TABLE").scan()["Items"]
        assert len(topics) == 6

    def test_cardcount_se_deriva_de_las_tarjetas_reales(self, aws, monkeypatch):
        # Observación #16: si cardCount se teclea, el catálogo miente.
        monkeypatch.setenv("TOPICS_TABLE", aws["topics"])
        monkeypatch.setenv("FLASHCARDS_TABLE", aws["flashcards"])

        import importlib
        import sys

        sys.path.insert(0, str(SEED_DIR.parent / "scripts"))
        seed = importlib.import_module("seed")
        importlib.reload(seed)
        seed.main()

        from boto3.dynamodb.conditions import Key
        from skillpath_common.db import table

        for topic in table("TOPICS_TABLE").scan()["Items"]:
            reales = table("FLASHCARDS_TABLE").query(
                KeyConditionExpression=Key("topicId").eq(topic["topicId"])
            )["Count"]
            assert int(topic["cardCount"]) == reales, topic["topicId"]

    def test_el_catalogo_sale_ordenado_por_nombre_sin_scan(self, aws, monkeypatch):
        # El GSI active-name-index existe para no hacer Scan y para devolver
        # el catálogo ya ordenado, como lo pinta el prototipo.
        monkeypatch.setenv("TOPICS_TABLE", aws["topics"])
        monkeypatch.setenv("FLASHCARDS_TABLE", aws["flashcards"])

        import importlib
        import sys

        sys.path.insert(0, str(SEED_DIR.parent / "scripts"))
        seed = importlib.import_module("seed")
        importlib.reload(seed)
        seed.main()

        from boto3.dynamodb.conditions import Key
        from skillpath_common.db import table

        items = table("TOPICS_TABLE").query(
            IndexName="active-name-index",
            KeyConditionExpression=Key("isActive").eq("true"),
        )["Items"]
        nombres = [i["name"] for i in items]
        assert nombres == sorted(nombres)
        assert len(nombres) == 6
