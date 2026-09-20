"""La plantilla de SAM es la fuente de verdad de la infraestructura.

Estas pruebas la leen y verifican que refleja las decisiones tomadas al
resolver las observaciones. Si alguien edita `template.yaml` y rompe una,
la prueba falla antes del despliegue.
"""

import pathlib

import pytest
import yaml

TEMPLATE = pathlib.Path(__file__).resolve().parents[2] / "template.yaml"


class _Loader(yaml.SafeLoader):
    """CloudFormation usa tags propios (!Ref, !Sub, !GetAtt).

    Se conservan como {"Ref": "UsersTable"} en vez de descartarlos: sin el
    valor no se podría comprobar a qué tabla apunta cada política IAM, que es
    justo lo que verifica `TestDatabasePerService`.
    """


def _keep_tag(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node)
    else:
        value = loader.construct_mapping(node)
    return {suffix: value}


yaml.add_multi_constructor("!", _keep_tag, Loader=_Loader)


@pytest.fixture(scope="module")
def template():
    return yaml.load(TEMPLATE.read_text(encoding="utf-8"), Loader=_Loader)


@pytest.fixture(scope="module")
def resources(template):
    return template["Resources"]


@pytest.fixture(scope="module")
def tables(resources):
    return {
        k: v["Properties"]
        for k, v in resources.items()
        if v["Type"] == "AWS::DynamoDB::Table"
    }


def _keys(props):
    return {k["KeyType"]: k["AttributeName"] for k in props["KeySchema"]}


def _index(props, name):
    for gsi in props.get("GlobalSecondaryIndexes", []):
        if gsi["IndexName"] == name:
            return gsi
    raise AssertionError(f"falta el índice {name}")


class TestTablas:
    def test_son_siete_como_dice_el_informe(self, tables):
        assert len(tables) == 7

    def test_todas_son_bajo_demanda(self, tables):
        # El costeo del informe asume PAY_PER_REQUEST; con capacidad
        # aprovisionada se pagaría aunque nadie use la app.
        for name, props in tables.items():
            assert props["BillingMode"] == "PAY_PER_REQUEST", name

    def test_todas_tienen_recuperacion_a_un_punto_en_el_tiempo(self, tables):
        for name, props in tables.items():
            assert props["PointInTimeRecoverySpecification"]["PointInTimeRecoveryEnabled"], name


class TestObservacion4:
    """La SK de las reviews debe ser compuesta y debe existir el GSI de vencimiento."""

    def test_la_sk_no_es_solo_el_cardid(self, tables):
        keys = _keys(tables["UserCardReviewsTable"])
        assert keys["HASH"] == "userId"
        assert keys["RANGE"] == "topicCardId"

    def test_existe_el_indice_de_vencimiento(self, tables):
        gsi = _index(tables["UserCardReviewsTable"], "due-index")
        assert _keys(gsi) == {"HASH": "userTopicKey", "RANGE": "nextReviewDate"}


class TestObservacion1:
    """Racha y XP viven en user-progress, sin tabla nueva."""

    def test_no_hay_tabla_de_estadisticas(self, tables):
        assert not [t for t in tables if "stat" in t.lower()]

    def test_user_progress_tiene_clave_compuesta(self, tables):
        # La SK admite tanto un topicId como el ítem especial "#STATS".
        assert _keys(tables["UserProgressTable"]) == {"HASH": "userId", "RANGE": "topicId"}


class TestBusquedaPorCorreo:
    """El correo se resuelve con un centinela, no con un índice secundario."""

    def test_la_tabla_de_usuarios_no_tiene_gsi(self, tables):
        # Un GSI por correo sería de consistencia eventual: quien acaba de
        # registrarse podría fallar al iniciar sesión. El centinela
        # "EMAIL#<correo>" se lee por clave primaria y es consistente, y de
        # paso impone la unicidad con una condición de escritura.
        assert "GlobalSecondaryIndexes" not in tables["UsersTable"]


class TestObservacion13:
    def test_la_api_es_http_no_rest(self, resources):
        apis = [v for v in resources.values() if "Api" in v["Type"]]
        assert all(v["Type"] == "AWS::Serverless::HttpApi" for v in apis)
        assert not any(v["Type"] == "AWS::Serverless::Api" for v in resources.values())


class TestObservacion3:
    def test_ninguna_ruta_lleva_el_userid(self, resources):
        for name, res in resources.items():
            for event in (res.get("Properties", {}).get("Events") or {}).values():
                path = event["Properties"]["Path"]
                assert "{userId}" not in path, f"{name}: {path}"
                assert "/users/" not in path, f"{name}: {path}"

    def test_solo_tres_rutas_son_publicas(self, resources):
        publicas = []
        for res in resources.values():
            for event in (res.get("Properties", {}).get("Events") or {}).values():
                props = event["Properties"]
                if (props.get("Auth") or {}).get("Authorizer") == "NONE":
                    publicas.append(f"{props['Method']} {props['Path']}")
        assert sorted(publicas) == [
            "GET /topics",
            "POST /auth/login",
            "POST /auth/register",
        ]

    def test_el_authorizer_protege_por_defecto(self, resources):
        auth = resources["Api"]["Properties"]["Auth"]
        # Que el default sea protegido significa que olvidar la anotación deja
        # la ruta cerrada, no abierta.
        assert auth["DefaultAuthorizer"] == "JwtAuthorizer"


def _dynamo_tables_of(resources, function):
    """Tablas sobre las que una función tiene permisos de DynamoDB."""
    concedidas = set()
    for policy in resources[function]["Properties"].get("Policies", []):
        if not isinstance(policy, dict):
            continue
        for tipo, valor in policy.items():
            if "DynamoDB" in tipo:
                # valor == {"TableName": {"Ref": "UsersTable"}}
                concedidas.add(valor["TableName"]["Ref"])
    return concedidas


class TestDatabasePerService:
    """Cada Lambda solo debe tener permisos sobre sus propias tablas.

    Es lo que convierte el patrón de una promesa del diagrama en una garantía
    real: aunque el código intentara leer la tabla de otro servicio, IAM lo
    rechazaría.
    """

    ESPERADO = {
        "AuthFunction": {"UsersTable"},
        "TopicsFunction": {"TopicsTable", "UserTopicsTable"},
        # UserTopics es de topics-service, pero flashcards necesita comprobar
        # que el usuario sigue el tema. Solo tiene permiso de LECTURA.
        "FlashcardsFunction": {"FlashcardsTable", "UserCardReviewsTable", "UserTopicsTable"},
        "ProgressFunction": {"UserProgressTable"},
        "QuizFunction": {"QuizAttemptsTable"},
    }

    @pytest.mark.parametrize("function", sorted(ESPERADO))
    def test_cada_servicio_solo_alcanza_sus_tablas(self, resources, function):
        assert _dynamo_tables_of(resources, function) == self.ESPERADO[function]

    def test_quiz_no_puede_leer_la_tabla_de_flashcards(self, resources):
        # Observación #7: necesita las tarjetas, pero las pide al servicio dueño.
        assert "FlashcardsTable" not in _dynamo_tables_of(resources, "QuizFunction")

    def test_flashcards_no_puede_escribir_en_la_tabla_de_progreso(self, resources):
        # Observación #6: calificar cambia el progreso, pero lo actualiza
        # progress-service, no flashcards-service.
        assert "UserProgressTable" not in _dynamo_tables_of(resources, "FlashcardsFunction")

    def test_el_acceso_de_flashcards_a_user_topics_es_de_solo_lectura(self, resources):
        politicas = resources["FlashcardsFunction"]["Properties"]["Policies"]
        for policy in politicas:
            for tipo, valor in policy.items():
                if "DynamoDB" in tipo and valor["TableName"]["Ref"] == "UserTopicsTable":
                    assert tipo == "DynamoDBReadPolicy"
                    return
        raise AssertionError("no se encontró la política sobre UserTopicsTable")

    @pytest.mark.parametrize(
        "function,destino",
        [
            ("FlashcardsFunction", "progress-service"),
            ("QuizFunction", "flashcards-service"),
            ("QuizFunction", "progress-service"),
        ],
    )
    def test_las_llamadas_entre_servicios_estan_autorizadas(self, resources, function, destino):
        politicas = resources[function]["Properties"]["Policies"]
        invocables = [
            p["LambdaInvokePolicy"]["FunctionName"]["Sub"]
            for p in politicas
            if isinstance(p, dict) and "LambdaInvokePolicy" in p
        ]
        assert any(destino in nombre for nombre in invocables), (
            f"{function} no puede invocar a {destino}"
        )


class TestObservacion17:
    def test_el_secreto_del_jwt_viene_de_ssm(self, template):
        # Nunca se escribe el secreto en la plantilla: se resuelve al desplegar.
        secreto = template["Globals"]["Function"]["Environment"]["Variables"]["JWT_SECRET"]
        assert "resolve:ssm-secure" in secreto["Sub"]


def test_el_runtime_coincide_con_el_python_local(template):
    assert template["Globals"]["Function"]["Runtime"] == "python3.11"


def test_la_memoria_coincide_con_la_del_costeo(template):
    # El informe calculó Lambda con 256 MB.
    assert template["Globals"]["Function"]["MemorySize"] == 256
