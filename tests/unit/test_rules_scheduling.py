"""Algoritmo de repetición espaciada (SM-2 simplificado).

Es el corazón de la app: define cuándo vuelve cada tarjeta y, por lo tanto,
todos los porcentajes de dominio que se muestran en pantalla. Ninguno de los
documentos originales lo especificaba (observación #9), así que estas pruebas
son la especificación ejecutable.
"""

import pytest
from skillpath_common.rules import (
    EASE_INITIAL,
    EASE_MAX,
    EASE_MIN,
    is_mastered,
    schedule,
    state_for,
)

NEW_CARD = {"repetitions": 0, "interval_days": 0, "ease": EASE_INITIAL}


class TestPrimerRepaso:
    def test_facil_programa_para_manana(self):
        r = schedule("easy", **NEW_CARD)
        assert r["repetitions"] == 1
        assert r["intervalDays"] == 1
        assert r["easeFactor"] == 2.6

    def test_dificil_programa_para_manana_como_minimo(self):
        # round(0 * 1.2) == 0, pero una tarjeta nunca debe reprogramarse a 0
        # días por "difícil": eso la dejaría repitiéndose dentro de la misma
        # sesión, que es el comportamiento de "olvidé".
        r = schedule("hard", **NEW_CARD)
        assert r["intervalDays"] == 1

    def test_olvide_la_devuelve_hoy_mismo(self):
        r = schedule("forgot", **NEW_CARD)
        assert r["intervalDays"] == 0
        assert r["repetitions"] == 0
        assert r["lapseIncrement"] == 1


class TestProgresionFacil:
    def test_secuencia_1_3_y_luego_multiplica(self):
        state = dict(NEW_CARD)
        intervals = []
        for _ in range(4):
            r = schedule("easy", **state)
            intervals.append(r["intervalDays"])
            state = {
                "repetitions": r["repetitions"],
                "interval_days": r["intervalDays"],
                "ease": r["easeFactor"],
            }
        # 1 día, 3 días, 3*2.7 = 8, 8*2.8 = 22
        assert intervals == [1, 3, 8, 22]

    def test_tres_faciles_seguidas_no_bastan_para_dominar(self):
        # A la tercera el intervalo es 8 días, por debajo de los 21 exigidos.
        state = dict(NEW_CARD)
        for _ in range(3):
            r = schedule("easy", **state)
            state = {
                "repetitions": r["repetitions"],
                "interval_days": r["intervalDays"],
                "ease": r["easeFactor"],
            }
        assert r["repetitions"] == 3
        assert r["state"] == "learning"

    def test_a_la_cuarta_facil_queda_dominada(self):
        state = dict(NEW_CARD)
        for _ in range(4):
            r = schedule("easy", **state)
            state = {
                "repetitions": r["repetitions"],
                "interval_days": r["intervalDays"],
                "ease": r["easeFactor"],
            }
        assert r["state"] == "mastered"


class TestFactorDeFacilidad:
    def test_nunca_baja_del_minimo(self):
        ease = EASE_INITIAL
        for _ in range(20):
            ease = schedule("forgot", repetitions=0, interval_days=0, ease=ease)["easeFactor"]
        assert ease == EASE_MIN

    def test_nunca_sube_del_maximo(self):
        ease = EASE_INITIAL
        for _ in range(20):
            ease = schedule("easy", repetitions=5, interval_days=30, ease=ease)["easeFactor"]
        assert ease == EASE_MAX

    @pytest.mark.parametrize(
        "rating,delta", [("forgot", -0.20), ("hard", -0.15), ("easy", +0.10)]
    )
    def test_cada_calificacion_mueve_el_factor(self, rating, delta):
        r = schedule(rating, repetitions=3, interval_days=10, ease=2.0)
        assert r["easeFactor"] == pytest.approx(2.0 + delta, abs=0.001)


class TestOlvidoReinicia:
    def test_una_tarjeta_dominada_deja_de_estarlo_al_olvidarla(self):
        r = schedule("forgot", repetitions=5, interval_days=40, ease=2.5)
        assert r["repetitions"] == 0
        assert r["intervalDays"] == 0
        assert r["state"] == "learning"  # ya fue repasada, así que no vuelve a "new"


class TestDefinicionDeDominado:
    """Observación #9: la definición no estaba en ningún documento y de ella
    dependen el 67%, el 58% y los «73 conceptos dominados» del prototipo."""

    @pytest.mark.parametrize(
        "reps,interval,esperado",
        [
            (3, 21, True),    # el umbral exacto
            (2, 60, False),   # muchos días pero pocos aciertos
            (10, 20, False),  # muchos aciertos pero aún sin espaciar 3 semanas
            (3, 20, False),
            (4, 25, True),
        ],
    )
    def test_umbral(self, reps, interval, esperado):
        assert is_mastered(reps, interval) is esperado

    def test_una_tarjeta_nunca_repasada_es_nueva(self):
        assert state_for(0, 0, reviewed=False) == "new"


def test_calificacion_desconocida_falla():
    with pytest.raises(ValueError):
        schedule("perfecto", **NEW_CARD)
