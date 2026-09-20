"""progress-service — progreso por tema, racha y XP (historias 4, 5 y 11).

Tabla propia: `user-progress`.

Por ahora solo expone la acción interna que necesita topics-service al
eliminar un mazo. El resto llega en la siguiente etapa.
"""

from skillpath_common.db import table
from skillpath_common.router import Router

router = Router("progress-service")

# Ítem especial, uno por usuario, que guarda racha y XP. La almohadilla ordena
# antes que cualquier letra, así que una sola Query trae estadísticas y temas.
STATS_KEY = "#STATS"


def _progress():
    return table("USER_PROGRESS_TABLE")


@router.internal("removeTopic")
def remove_topic(data):
    """Elimina el progreso de un usuario en un tema.

    Se invoca al borrar un mazo propio (historia 8). Sin esto, el mazo
    eliminado seguiría apareciendo en la pantalla «Mi progreso».
    """
    _progress().delete_item(Key={"userId": data["userId"], "topicId": data["topicId"]})
    return {"removed": True}


lambda_handler = router.as_handler()
