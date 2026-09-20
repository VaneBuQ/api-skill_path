"""La especificación de infraestructura respeta las decisiones de diseño.

El despliegue es manual, así que estas pruebas son lo que impide que la guía
de la consola contradiga lo acordado. Cada una apunta a la observación que
resolvió.
"""

import pytest

from infra.spec import (
    MEMORY_MB,
    RUNTIME,
    SERVICES,
    TABLES,
    all_routes,
    env_for,
    table_name,
)


class TestTablas:
    def test_son_siete_como_dice_el_informe(self):
        assert len(TABLES) == 7

    def test_cada_tabla_tiene_un_solo_servicio_dueno(self):
        for short, spec in TABLES.items():
            assert spec["owner"] in SERVICES, short

    def test_el_nombre_lleva_el_entorno(self):
        # Así dev y prod conviven en la misma cuenta sin pisarse.
        assert table_name("dev", "users") == "skillpath-dev-users"
        assert table_name("prod", "users") == "skillpath-prod-users"


class TestObservacion4:
    """Las reviews deben poder consultarse por tema y por vencimiento."""

    def test_la_sk_no_es_solo_el_cardid(self):
        spec = TABLES["user-card-reviews"]
        assert spec["pk"][0] == "userId"
        assert spec["sk"][0] == "topicCardId"

    def test_existe_el_indice_de_vencimiento(self):
        index = TABLES["user-card-reviews"]["indexes"][0]
        assert index["name"] == "due-index"
        assert index["pk"][0] == "userTopicKey"
        assert index["sk"][0] == "nextReviewDate"


class TestObservacion1:
    """Racha y XP viven en user-progress, sin tabla nueva."""

    def test_no_hay_tabla_de_estadisticas(self):
        assert not [t for t in TABLES if "stat" in t]

    def test_user_progress_tiene_clave_compuesta(self):
        spec = TABLES["user-progress"]
        assert (spec["pk"][0], spec["sk"][0]) == ("userId", "topicId")


class TestBusquedaPorCorreo:
    def test_la_tabla_de_usuarios_no_tiene_indices(self):
        # El centinela "EMAIL#<correo>" se lee por clave primaria y es
        # fuertemente consistente; un índice secundario no lo sería.
        assert TABLES["users"]["indexes"] == []


class TestHistoria8:
    """Un mazo propio es un tema privado, no una entidad nueva."""

    def test_no_hay_tabla_de_mazos(self):
        assert not [t for t in TABLES if "deck" in t or "mazo" in t]

    def test_el_catalogo_se_filtra_por_visibilidad(self):
        index = TABLES["topics"]["indexes"][0]
        assert index["name"] == "catalog-index"
        assert index["pk"][0] == "visibility"

    def test_los_temas_llevan_dueno(self):
        assert "ownerId" in TABLES["topics"]["attributes"]

    def test_topics_service_puede_escribir_temas(self):
        # Antes solo leía el catálogo; ahora crea mazos propios.
        assert SERVICES["topics-service"]["tables"]["topics"] == "crud"

    def test_topics_service_no_escribe_tarjetas_ni_progreso(self):
        # Crear y borrar mazos toca datos de otros servicios: se los pide.
        tablas = SERVICES["topics-service"]["tables"]
        assert "flashcards" not in tablas
        assert "user-progress" not in tablas
        assert set(SERVICES["topics-service"]["invokes"]) == {
            "flashcards-service",
            "progress-service",
        }


class TestObservacion3:
    def test_ninguna_ruta_lleva_el_userid(self):
        for method, path, _, _, service in all_routes():
            assert "{userId}" not in path, f"{service}: {method} {path}"
            assert not path.startswith("/users/"), f"{service}: {method} {path}"

    def test_solo_tres_rutas_son_publicas(self):
        publicas = sorted(
            f"{m} {p}" for m, p, auth, _, _ in all_routes() if auth == "NONE"
        )
        assert publicas == ["GET /topics", "POST /auth/login", "POST /auth/register"]

    def test_todo_lo_personal_cuelga_de_me(self):
        for method, path, auth, _, _ in all_routes():
            if auth == "NONE":
                continue
            personal = path.startswith("/me/") or path in ("/auth/me", "/progress")
            recurso = path.startswith(("/topics/", "/flashcards/", "/quiz/", "/progress/"))
            assert personal or recurso, f"{method} {path}"


class TestDatabasePerService:
    """Cada servicio solo declara permisos sobre sus propias tablas."""

    @pytest.mark.parametrize("service", sorted(SERVICES))
    def test_no_accede_a_tablas_de_otro(self, service):
        for short in SERVICES[service]["tables"]:
            owner = TABLES[short]["owner"]
            if owner == service:
                continue
            # La única excepción permitida es lectura, nunca escritura.
            assert SERVICES[service]["tables"][short] == "read", (
                f"{service} escribe en {short}, que es de {owner}"
            )

    def test_quiz_no_alcanza_la_tabla_de_flashcards(self):
        assert "flashcards" not in SERVICES["quiz-service"]["tables"]
        assert "flashcards-service" in SERVICES["quiz-service"]["invokes"]

    def test_flashcards_no_alcanza_la_tabla_de_progreso(self):
        assert "user-progress" not in SERVICES["flashcards-service"]["tables"]
        assert "progress-service" in SERVICES["flashcards-service"]["invokes"]

    def test_cada_tabla_tiene_exactamente_un_escritor(self):
        for short, spec in TABLES.items():
            escritores = [
                s for s, cfg in SERVICES.items() if cfg["tables"].get(short) == "crud"
            ]
            assert escritores == [spec["owner"]], f"{short}: {escritores}"


class TestVariablesDeEntorno:
    def test_cada_servicio_recibe_los_nombres_de_sus_tablas(self):
        env = env_for("dev", "flashcards-service")
        assert env["FLASHCARDS_TABLE"] == "skillpath-dev-flashcards"
        assert env["USER_CARD_REVIEWS_TABLE"] == "skillpath-dev-user-card-reviews"

    def test_cada_servicio_recibe_los_nombres_de_quien_invoca(self):
        env = env_for("dev", "topics-service")
        assert env["FLASHCARDS_FUNCTION"] == "skillpath-dev-flashcards-service"
        assert env["PROGRESS_FUNCTION"] == "skillpath-dev-progress-service"

    def test_ninguna_variable_contiene_el_secreto(self):
        # El valor real se escribe a mano en la consola, nunca en el repo.
        for service in SERVICES:
            assert env_for("dev", service)["JWT_SECRET"].startswith("<")


def test_el_runtime_coincide_con_el_python_local():
    assert RUNTIME == "python3.11"


def test_la_memoria_coincide_con_la_del_costeo():
    assert MEMORY_MB == 256


def test_cada_servicio_tiene_codigo_y_descripcion():
    for service, spec in SERVICES.items():
        assert spec["code"].startswith("services/"), service
        assert spec["description"], service
