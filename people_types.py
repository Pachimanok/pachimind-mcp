"""Public MCP input contracts; the API independently validates every command."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')

class PersonChanges(Input):
    nombre: str | None = Field(default=None, min_length=1, max_length=200)
    aliases: list[str] | None = None
    organizacion: str | None = None
    funcion: str | None = None
    relacion_conmigo: str | None = None
    ambitos: list[Literal['Trabajo', 'Apostólico', 'Colegios', 'Formación']] | None = None
    contactos_profesionales: dict[Literal['email_profesional', 'telefono_profesional', 'perfil_profesional'], str] | None = None
    notas_manuales: str | None = None
    tipo: Literal['persona', 'idea', 'recurso', 'nota'] | None = None

class PersonEvidence(Input):
    field: str
    source_id: str
    quote: str = Field(min_length=1, max_length=4000)

class NoteLink(Input):
    target_id: str
    target_revision: str
    relation: Literal['participó en', 'mencionado en', 'trabaja con', 'vinculado al proyecto', 'fuente', 'relacionado con', 'referencia']
    action: Literal['add', 'remove'] = 'add'
    evidence: PersonEvidence | None = None

class ReservedSegment(Input):
    source_reference: str
    start_seconds: int = Field(ge=0)
    end_seconds: int = Field(ge=0)
