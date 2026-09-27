#!/usr/bin/env python3
"""Carga el catálogo de temas y sus flashcards en DynamoDB.

`cardCount` NO se escribe a mano: se deriva de las tarjetas realmente
insertadas (observación #16). Si se teclea, el catálogo acaba anunciando 36
conceptos donde solo hay 15, y el gate del quiz y los porcentajes de progreso
dejan de cuadrar.

Uso:
    python scripts/seed.py                      # contra AWS (usa STAGE)
    DYNAMODB_ENDPOINT=http://localhost:8000 \
        python scripts/seed.py                  # contra DynamoDB Local
"""

import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "shared"))

import boto3  # noqa: E402
from common import to_iso  # noqa: E402

SEED_DIR = pathlib.Path(__file__).resolve().parents[1] / "seed"
STAGE = os.environ.get("STAGE", "dev")

# Si no se pasan explícitamente, se deducen del stage, igual que hace SAM.
# Los nombres coinciden con los que crean los serverless.yml.
os.environ.setdefault("TOPICS_TABLE", f"topics-catalog-{STAGE}")
os.environ.setdefault("CARDS_TABLE", f"flashcards-cards-{STAGE}")

RESOURCE = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def table(env_var):
    return RESOURCE.Table(os.environ[env_var])


def load(name: str):
    return json.loads((SEED_DIR / name).read_text(encoding="utf-8"))


def seed_cards(topic_id: str) -> int:
    """Inserta las tarjetas de un tema y devuelve cuántas quedaron."""
    path = SEED_DIR / f"flashcards-{topic_id}.json"
    if not path.exists():
        print(f"   ⚠  sin archivo de tarjetas para «{topic_id}»")
        return 0

    cards = json.loads(path.read_text(encoding="utf-8"))
    cards_table = table("CARDS_TABLE")
    now = to_iso()

    with cards_table.batch_writer() as batch:
        for position, card in enumerate(cards, start=1):
            batch.put_item(
                Item={
                    "topicId": topic_id,
                    # Los ceros a la izquierda hacen que la SK ordene como
                    # número: crd_0002 va antes que crd_0010.
                    "cardId": f"crd_{position:04d}",
                    "question": card["question"],
                    "answer": card["answer"],
                    "hint": card.get("hint"),
                    "position": position,
                        "createdAt": now,
                }
            )
    return len(cards)


def main() -> int:
    topics = load("topics.json")
    topics_table = table("TOPICS_TABLE")
    now = to_iso()
    total_cards = 0

    print(f"Cargando semilla en el stage «{STAGE}»\n")

    for topic in topics:
        topic_id = topic["topicId"]
        card_count = seed_cards(topic_id)
        total_cards += card_count

        topics_table.put_item(
            Item={
                "topicId": topic_id,
                "name": topic["name"],
                "description": topic["description"],
                "icon": topic["icon"],
                "level": topic["level"],
                "category": topic.get("category", "General"),
                # Derivado, nunca tecleado.
                "cardCount": card_count,
                # Los temas del catálogo son públicos. Los mazos que crea el
                # usuario llevan "private" y no salen aquí.
                "visibility": "public",
                "createdAt": now,
            }
        )
        print(f"   ✓ {topic['name']:28s} {card_count:3d} tarjetas")

    print(f"\nListo: {len(topics)} temas, {total_cards} tarjetas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
