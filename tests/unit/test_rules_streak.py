"""Racha de días consecutivos y XP (observación #1).

HU5 pide que la racha se reinicie a 0 si el usuario no estudió el día anterior.
Se resuelve con dos funciones: una al escribir (cuando el usuario estudia) y
otra al leer, para no tener que correr un proceso nocturno sobre todos los
usuarios.
"""

import pytest
from skillpath_common.rules import XP_PER_CARD, XP_PER_QUIZ, next_streak, streak_as_read

HOY = "2026-09-20"
AYER = "2026-09-19"
ANTEAYER = "2026-09-18"


class TestAlEstudiar:
    def test_primer_dia_de_la_vida(self):
        assert next_streak(0, None, HOY, AYER) == 1

    def test_estudio_ayer_suma_uno(self):
        assert next_streak(12, AYER, HOY, AYER) == 13

    def test_segunda_sesion_del_mismo_dia_no_suma(self):
        # Repasar 30 tarjetas en un día es una racha de 1, no de 30.
        assert next_streak(12, HOY, HOY, AYER) == 12

    def test_racha_rota_vuelve_a_empezar_en_uno(self):
        assert next_streak(12, ANTEAYER, HOY, AYER) == 1

    def test_racha_rota_hace_meses(self):
        assert next_streak(40, "2026-01-05", HOY, AYER) == 1


class TestAlLeer:
    def test_estudio_hoy_muestra_la_racha(self):
        assert streak_as_read(12, HOY, HOY, AYER) == 12

    def test_estudio_ayer_la_racha_sigue_viva(self):
        # Aún no ha estudiado hoy, pero la racha no se ha roto todavía.
        assert streak_as_read(12, AYER, HOY, AYER) == 12

    def test_no_estudio_ayer_la_racha_se_muestra_en_cero(self):
        # HU5: "GIVEN el usuario no repasó el día anterior THEN la racha se
        # reinicia a 0". Se calcula en la lectura, sin proceso nocturno.
        assert streak_as_read(12, ANTEAYER, HOY, AYER) == 0

    def test_usuario_que_nunca_estudio(self):
        assert streak_as_read(0, None, HOY, AYER) == 0


class TestExperiencia:
    def test_ocho_tarjetas_dan_cuarenta_xp(self):
        # El prototipo anuncia "+40 XP disponibles hoy" en la pantalla inicial.
        assert 8 * XP_PER_CARD == 40

    def test_el_quiz_da_ciento_veinte(self):
        # "+120 XP al completar" (p.12) y "+120 XP obtenidos" (p.14).
        assert XP_PER_QUIZ == 120


@pytest.mark.parametrize("dias", [1, 7, 12, 365])
def test_la_racha_crece_de_uno_en_uno(dias):
    racha = 0
    ultimo = None
    from datetime import date, timedelta

    inicio = date(2026, 1, 1)
    for i in range(dias):
        hoy = (inicio + timedelta(days=i)).isoformat()
        ayer = (inicio + timedelta(days=i - 1)).isoformat()
        racha = next_streak(racha, ultimo, hoy, ayer)
        ultimo = hoy
    assert racha == dias
